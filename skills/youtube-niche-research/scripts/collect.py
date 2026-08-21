import argparse
import calendar
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from analyze import (
    calculate_video_metrics,
    clean_comments,
    comment_evidence_state,
    extract_phrases,
    is_qualified_video,
    metadata_language_match,
    parse_duration,
    project_status,
)


READ_ONLY_RESOURCES = {
    "search",
    "videos",
    "channels",
    "playlistItems",
    "commentThreads",
}
ERROR_STATES = {
    "commentsDisabled": "comments_disabled",
    "quotaExceeded": "quota_exhausted",
    "dailyLimitExceeded": "quota_exhausted",
    "rateLimitExceeded": "rate_limited",
    "keyInvalid": "invalid_key",
    "accessNotConfigured": "api_not_enabled",
}
_RESOURCE_UNITS = {"search": 100}
_CACHE_SECONDS = {"commentThreads": 12 * 3600}


def estimate_quota(query_count: int, results_per_query: int = 25) -> dict:
    candidate_upper_bound = query_count * results_per_query
    search_units = query_count * 100
    video_detail_units = math.ceil(candidate_upper_bound / 50)
    channel_detail_units = math.ceil(candidate_upper_bound / 50)
    playlist_units = candidate_upper_bound
    baseline_video_units = math.ceil(candidate_upper_bound * 30 / 50)
    comment_units = candidate_upper_bound
    upper_bound_units = sum(
        (
            search_units,
            video_detail_units,
            channel_detail_units,
            playlist_units,
            baseline_video_units,
            comment_units,
        )
    )
    return {
        "candidate_upper_bound": candidate_upper_bound,
        "search_units": search_units,
        "video_detail_units": video_detail_units,
        "channel_detail_units": channel_detail_units,
        "playlist_units": playlist_units,
        "baseline_video_units": baseline_video_units,
        "comment_units": comment_units,
        "upper_bound_units": upper_bound_units,
    }


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    redacted_query = urlencode(
        [
            (name, "REDACTED" if name == "key" else value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment)
    )


def _safe_params(params: dict) -> dict:
    return {name: value for name, value in params.items() if name != "key"}


def canonical_request_key(resource: str, params: dict) -> str:
    params_json = json.dumps(
        _safe_params(params), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    material = f"{resource}\n{params_json}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def load_api_key(workspace: Path, environ: Mapping[str, str]) -> str:
    environment_value = environ.get("YOUTUBE_API_KEY", "").strip()
    if environment_value:
        return environment_value

    dotenv = workspace / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if line.startswith("YOUTUBE_API_KEY="):
                file_value = line.removeprefix("YOUTUBE_API_KEY=").strip()
                if file_value:
                    return file_value
                break

    raise RuntimeError("YOUTUBE_API_KEY is not configured")


class ResponseCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS responses (
                    request_key TEXT PRIMARY KEY,
                    resource TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                )
                """
            )

    def get(
        self, key: str, max_age_seconds: int, now: datetime
    ) -> dict | list | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json, retrieved_at FROM responses WHERE request_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        payload_json, retrieved_at_text = row
        retrieved_at = datetime.fromisoformat(retrieved_at_text)
        if (now - retrieved_at).total_seconds() > max_age_seconds:
            return None
        return json.loads(payload_json)

    def put(
        self,
        key: str,
        payload: dict | list,
        retrieved_at: datetime,
        resource: str,
        params: dict,
    ) -> None:
        safe_params = _safe_params(params)
        params_json = json.dumps(safe_params, ensure_ascii=False, sort_keys=True)
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO responses (
                    request_key,
                    resource,
                    params_json,
                    payload_json,
                    retrieved_at,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_key) DO UPDATE SET
                    resource = excluded.resource,
                    params_json = excluded.params_json,
                    payload_json = excluded.payload_json,
                    retrieved_at = excluded.retrieved_at,
                    content_hash = excluded.content_hash
                """,
                (
                    key,
                    resource,
                    params_json,
                    payload_json,
                    retrieved_at.isoformat(),
                    content_hash,
                ),
            )


class YouTubeAPIError(RuntimeError):
    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state


@dataclass(frozen=True)
class ResearchConfig:
    research_name: str
    queries: tuple[str, ...]
    target_language: str
    min_duration_seconds: int
    max_duration_seconds: int
    lookback_months: int | None
    results_per_query: int = 25
    comments_per_video: int = 100


class YouTubeGateway(Protocol):
    quota_ledger: dict

    def search(
        self, query: str, published_after: str | None, max_results: int
    ) -> list[str]: ...

    def video_details(self, video_ids: list[str]) -> list[dict]: ...

    def channel_details(self, channel_ids: list[str]) -> list[dict]: ...

    def channel_uploads(
        self, channel_id: str, uploads_playlist_id: str, max_results: int
    ) -> list[str]: ...

    def comments(
        self, video_id: str, max_results: int, order: str, text_format: str
    ) -> dict: ...


class YouTubeAPIClient:
    def __init__(self, api_key: str, cache: ResponseCache, now=None):
        if not api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not configured")
        self._api_key = api_key
        self._cache = cache
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.quota_ledger = {
            "actual_units": 0,
            "cache_hits": 0,
            "by_resource": {},
        }

    def get(
        self, resource: str, params: dict, max_age_seconds: int | None = None
    ) -> dict:
        if resource not in READ_ONLY_RESOURCES:
            raise ValueError(f"Unsupported read-only resource: {resource}")

        now = self._now()
        cache_seconds = max_age_seconds or _CACHE_SECONDS.get(resource, 24 * 3600)
        request_key = canonical_request_key(resource, params)
        cached = self._cache.get(request_key, cache_seconds, now)
        if cached is not None:
            self.quota_ledger["cache_hits"] += 1
            return cached

        request_params = dict(params)
        request_params["key"] = self._api_key
        url = f"https://www.googleapis.com/youtube/v3/{resource}?{urlencode(request_params)}"
        request = Request(url, method="GET")
        units = _RESOURCE_UNITS.get(resource, 1)
        self.quota_ledger["actual_units"] += units
        by_resource = self.quota_ledger["by_resource"]
        by_resource[resource] = by_resource.get(resource, 0) + units

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            state = _http_error_state(error)
            raise YouTubeAPIError(
                state,
                f"YouTube API request failed ({state}): {redact_url(url)}",
            ) from None
        except URLError:
            raise YouTubeAPIError(
                "network_error",
                f"YouTube API network request failed: {redact_url(url)}",
            ) from None

        self._cache.put(request_key, payload, now, resource, params)
        return payload

    def search(
        self, query: str, published_after: str | None, max_results: int
    ) -> list[str]:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max_results, 25),
        }
        if published_after:
            params["publishedAfter"] = published_after
        payload = self.get("search", params)
        return [
            item["id"]["videoId"]
            for item in payload.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

    def video_details(self, video_ids: list[str]) -> list[dict]:
        if not video_ids:
            return []
        payload = self.get(
            "videos",
            {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(video_ids),
                "maxResults": min(len(video_ids), 50),
            },
        )
        return [_normalize_video(item) for item in payload.get("items", [])]

    def channel_details(self, channel_ids: list[str]) -> list[dict]:
        if not channel_ids:
            return []
        payload = self.get(
            "channels",
            {
                "part": "contentDetails,statistics",
                "id": ",".join(channel_ids),
                "maxResults": min(len(channel_ids), 50),
            },
        )
        return [_normalize_channel(item) for item in payload.get("items", [])]

    def channel_uploads(
        self, channel_id: str, uploads_playlist_id: str, max_results: int
    ) -> list[str]:
        del channel_id
        payload = self.get(
            "playlistItems",
            {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 30),
            },
        )
        return [
            item["contentDetails"]["videoId"]
            for item in payload.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

    def comments(
        self,
        video_id: str,
        max_results: int,
        order: str = "relevance",
        text_format: str = "plainText",
    ) -> dict:
        payload = self.get(
            "commentThreads",
            {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": min(max_results, 100),
                "order": order,
                "textFormat": text_format,
            },
        )
        return {
            "state": "available",
            "comments": [
                _normalize_api_comment(item) for item in payload.get("items", [])
            ],
        }


def _http_error_state(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        reason = payload["error"]["errors"][0]["reason"]
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError):
        return "api_error"
    return ERROR_STATES.get(reason, "api_error")


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_video(item: dict) -> dict:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    return {
        "video_id": item["id"],
        "title": snippet.get("title", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "duration": item.get("contentDetails", {}).get("duration", "PT0S"),
        "views": _integer(statistics.get("viewCount")),
        "public_comment_count": _integer(statistics.get("commentCount")),
        "source_language": snippet.get("defaultLanguage")
        or snippet.get("defaultAudioLanguage"),
        "live_state": snippet.get("liveBroadcastContent", "none"),
    }


def _normalize_channel(item: dict) -> dict:
    statistics = item.get("statistics", {})
    hidden = statistics.get("hiddenSubscriberCount", False)
    subscriber_count = None if hidden else _integer(statistics.get("subscriberCount"))
    return {
        "channel_id": item["id"],
        "subscriber_count": subscriber_count,
        "uploads_playlist_id": item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads"),
    }


def _normalize_api_comment(item: dict) -> dict:
    thread_snippet = item.get("snippet", {})
    top_level = thread_snippet.get("topLevelComment", {})
    snippet = top_level.get("snippet", {})
    return {
        "comment_id": top_level.get("id") or item.get("id", ""),
        "text": snippet.get("textOriginal") or snippet.get("textDisplay", ""),
        "like_count": _integer(snippet.get("likeCount")),
        "published_at": snippet.get("publishedAt", ""),
        "reply_count": _integer(thread_snippet.get("totalReplyCount")),
    }


def _published_after(retrieved_at: datetime, lookback_months: int | None) -> str | None:
    if not lookback_months or lookback_months < 0:
        return None
    month_index = retrieved_at.year * 12 + retrieved_at.month - 1 - lookback_months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(retrieved_at.day, calendar.monthrange(year, month)[1])
    value = retrieved_at.replace(year=year, month=month, day=day)
    return value.isoformat().replace("+00:00", "Z")


def _batches(values: list[str], size: int = 50):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _failure(error: YouTubeAPIError, stage: str, video_id: str | None = None) -> dict:
    result = {"state": error.state, "stage": stage, "message": str(error)}
    if video_id:
        result["video_id"] = video_id
    return result


def _document(
    config: ResearchConfig,
    retrieved_at: datetime,
    collection_status: str,
    quota_ledger: dict,
    per_query_counts: dict,
    evidence_items: list[dict],
    failures: list[dict],
) -> dict:
    return {
        "schema_version": "1.0",
        "run": {
            "research_name": config.research_name,
            "queries": list(config.queries),
            "target_language": config.target_language,
            "lookback_months": config.lookback_months,
            "retrieved_at": retrieved_at.isoformat(),
            "collection_status": collection_status,
            "quota": quota_ledger,
            "per_query_candidate_counts": per_query_counts,
        },
        "statuses": project_status(evidence_items),
        "evidence": evidence_items,
        "failures": failures,
    }


def collect_evidence(
    config: ResearchConfig, gateway: YouTubeGateway, retrieved_at: datetime
) -> dict:
    published_after = _published_after(retrieved_at, config.lookback_months)
    per_query_counts = {}
    provenance = {}
    failures = []
    evidence_items = []

    try:
        for query in config.queries:
            video_ids = gateway.search(
                query, published_after, min(config.results_per_query, 25)
            )
            per_query_counts[query] = len(video_ids)
            for video_id in video_ids:
                provenance.setdefault(video_id, [])
                if query not in provenance[video_id]:
                    provenance[video_id].append(query)

        candidate_ids = list(provenance)
        candidates = []
        for batch in _batches(candidate_ids):
            candidates.extend(gateway.video_details(batch))

        channel_ids = list(dict.fromkeys(item["channel_id"] for item in candidates))
        channels = []
        for batch in _batches(channel_ids):
            channels.extend(gateway.channel_details(batch))
        channels_by_id = {item["channel_id"]: item for item in channels}

        baseline_ids_by_channel = {}
        all_baseline_ids = []
        for channel_id in channel_ids:
            channel = channels_by_id.get(channel_id, {})
            uploads_playlist_id = channel.get("uploads_playlist_id")
            if not uploads_playlist_id:
                baseline_ids_by_channel[channel_id] = []
                continue
            video_ids = gateway.channel_uploads(
                channel_id, uploads_playlist_id, max_results=30
            )
            baseline_ids_by_channel[channel_id] = video_ids
            all_baseline_ids.extend(video_ids)

        baseline_videos = []
        for batch in _batches(list(dict.fromkeys(all_baseline_ids))):
            baseline_videos.extend(gateway.video_details(batch))
        baseline_by_id = {item["video_id"]: item for item in baseline_videos}
    except YouTubeAPIError as error:
        if error.state in {"invalid_key", "api_not_enabled"}:
            raise
        failures.append(_failure(error, "metadata"))
        return _document(
            config,
            retrieved_at,
            "partial",
            _quota_ledger(config, gateway),
            per_query_counts,
            evidence_items,
            failures,
        )

    config_for_qualification = {
        "published_after": published_after or "0001-01-01T00:00:00+00:00",
        "min_duration_seconds": config.min_duration_seconds,
        "max_duration_seconds": config.max_duration_seconds,
    }

    for candidate in candidates:
        channel_id = candidate["channel_id"]
        baseline = []
        for video_id in baseline_ids_by_channel.get(channel_id, []):
            item = baseline_by_id.get(video_id)
            if item is None:
                continue
            duration_seconds = parse_duration(item["duration"])
            if not (
                item["published_at"] >= config_for_qualification["published_after"]
                and config.min_duration_seconds
                <= duration_seconds
                <= config.max_duration_seconds
                and item["live_state"] == "none"
            ):
                continue
            baseline.append(
                {"views": item["views"], "published_at": item["published_at"]}
            )

        language_match = metadata_language_match(
            candidate.get("source_language"), config.target_language
        )
        duration_seconds = parse_duration(candidate["duration"])
        item = {
            "evidence_id": f"yt-{candidate['video_id']}",
            "video_id": candidate["video_id"],
            "title": candidate["title"],
            "channel_id": channel_id,
            "channel_title": candidate.get("channel_title", ""),
            "published_at": candidate["published_at"],
            "duration_seconds": duration_seconds,
            "views": candidate["views"],
            "public_comment_count": candidate.get("public_comment_count", 0),
            "live_state": candidate["live_state"],
            "language_match": language_match,
            "baseline_count": len(baseline),
            "search_provenance": provenance[candidate["video_id"]],
        }
        if baseline:
            item.update(calculate_video_metrics(candidate, baseline, retrieved_at))
        else:
            item.update(
                {
                    "age_days": None,
                    "view_velocity": None,
                    "channel_median_views": None,
                    "channel_median_view_velocity": None,
                    "raw_outlier_multiple": None,
                    "age_adjusted_outlier_multiple": None,
                }
            )

        item["qualified_performance"] = is_qualified_video(
            item, config_for_qualification
        )
        multiple = item.get("age_adjusted_outlier_multiple")
        item["strong_signal"] = bool(
            item["qualified_performance"] and multiple is not None and multiple >= 3
        )
        channel = channels_by_id.get(channel_id, {})
        subscriber_count = channel.get("subscriber_count")
        item["channel_subscriber_count"] = subscriber_count
        item["view_to_subscriber_ratio"] = (
            round(candidate["views"] / subscriber_count, 4)
            if subscriber_count
            else None
        )
        item.update(
            {
                "comments_state": "not_requested",
                "fetched_comment_count": 0,
                "cleaned_comment_count": 0,
                "comments": [],
                "comment_phrases": [],
                "recurring_need_phrases": [],
                "audience_demand": False,
            }
        )

        if item["qualified_performance"]:
            try:
                comment_result = gateway.comments(
                    candidate["video_id"],
                    min(config.comments_per_video, 100),
                    order="relevance",
                    text_format="plainText",
                )
            except YouTubeAPIError as error:
                if error.state == "comments_disabled":
                    item["comments_state"] = "comments_disabled"
                    evidence_items.append(item)
                    continue
                if error.state in {"invalid_key", "api_not_enabled"}:
                    raise
                failures.append(_failure(error, "comments", candidate["video_id"]))
                break

            normalized_comments = [
                _normalize_collected_comment(comment)
                for comment in comment_result.get("comments", [])
            ]
            cleaned_comments = clean_comments(normalized_comments)
            phrases = extract_phrases(cleaned_comments)
            item.update(
                {
                    "comments_state": comment_result.get("state", "available"),
                    "fetched_comment_count": len(normalized_comments),
                    "cleaned_comment_count": len(cleaned_comments),
                    "comments": normalized_comments,
                    "comment_phrases": phrases,
                    "recurring_need_phrases": [
                        phrase["phrase"] for phrase in phrases if phrase["count"] >= 2
                    ],
                }
            )
            item["audience_demand"] = comment_evidence_state(item)

        evidence_items.append(item)

    collection_status = "partial" if failures else "complete"
    return _document(
        config,
        retrieved_at,
        collection_status,
        _quota_ledger(config, gateway),
        per_query_counts,
        evidence_items,
        failures,
    )


def _normalize_collected_comment(comment: dict) -> dict:
    return {
        "comment_id": str(comment.get("comment_id", "")),
        "text": str(comment.get("text", "")),
        "like_count": _integer(comment.get("like_count")),
        "published_at": str(comment.get("published_at", "")),
        "reply_count": _integer(comment.get("reply_count")),
    }


def _quota_ledger(config: ResearchConfig, gateway: YouTubeGateway) -> dict:
    ledger = dict(getattr(gateway, "quota_ledger", {}))
    ledger["estimated_upper_bound_units"] = estimate_quota(
        len(config.queries), config.results_per_query
    )["upper_bound_units"]
    return ledger


def write_run(evidence: dict, workspace: Path, run_slug: str) -> Path:
    retrieved_at = datetime.fromisoformat(
        evidence["run"]["retrieved_at"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    timestamp = retrieved_at.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^\w-]+", "-", run_slug.strip().lower()).strip("-") or "run"
    run_directory = (
        workspace / ".youtube-niche-research" / "runs" / f"{timestamp}-{slug}"
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_directory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect read-only YouTube evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate_parser = subparsers.add_parser("estimate")
    estimate_parser.add_argument("--queries", type=int, required=True)
    estimate_parser.add_argument("--results-per-query", type=int, default=25)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--confirm-read-only-scan", action="store_true")
    run_parser.add_argument("--research-name", default="YouTube research")
    run_parser.add_argument("--query", action="append")
    run_parser.add_argument("--target-language", default="English")
    run_parser.add_argument("--min-duration-seconds", type=int, default=480)
    run_parser.add_argument("--max-duration-seconds", type=int, default=1200)
    run_parser.add_argument("--lookback-months", type=int, default=24)
    run_parser.add_argument("--results-per-query", type=int, default=25)
    run_parser.add_argument("--comments-per-video", type=int, default=100)
    run_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    run_parser.add_argument("--run-slug", default="research")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "estimate":
        print(
            json.dumps(
                estimate_quota(args.queries, args.results_per_query),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if not args.confirm_read_only_scan:
        print(
            "Live collection requires explicit confirmation after quota review.",
            file=sys.stderr,
        )
        return 2
    if not args.query:
        print("At least one --query is required.", file=sys.stderr)
        return 2

    config = ResearchConfig(
        research_name=args.research_name,
        queries=tuple(args.query),
        target_language=args.target_language,
        min_duration_seconds=args.min_duration_seconds,
        max_duration_seconds=args.max_duration_seconds,
        lookback_months=args.lookback_months,
        results_per_query=args.results_per_query,
        comments_per_video=args.comments_per_video,
    )
    api_key = load_api_key(args.workspace, os.environ)
    cache = ResponseCache(
        args.workspace / ".youtube-niche-research" / "cache.sqlite3"
    )
    gateway = YouTubeAPIClient(api_key, cache)
    evidence = collect_evidence(config, gateway, datetime.now(timezone.utc))
    run_directory = write_run(evidence, args.workspace, args.run_slug)
    print(run_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
