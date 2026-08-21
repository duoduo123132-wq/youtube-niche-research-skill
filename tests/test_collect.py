import json
import sqlite3
from dataclasses import replace
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

import collect as collect_module

from collect import (
    ResearchConfig,
    ResponseCache,
    YouTubeAPIClient,
    YouTubeAPIError,
    canonical_request_key,
    collect_evidence,
    estimate_quota,
    load_api_key,
    main,
    redact_url,
    write_run,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "collection"
NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


class FakeGateway:
    def __init__(self):
        self.searches = json.loads(
            (FIXTURE_ROOT / "search-ai.json").read_text(encoding="utf-8")
        )
        self.candidates = {
            item["video_id"]: item
            for item in json.loads(
                (FIXTURE_ROOT / "videos.json").read_text(encoding="utf-8")
            )
        }
        self.channels_by_id = {
            item["channel_id"]: item
            for item in json.loads(
                (FIXTURE_ROOT / "channels.json").read_text(encoding="utf-8")
            )
        }
        self.baseline_sets = json.loads(
            (FIXTURE_ROOT / "baselines.json").read_text(encoding="utf-8")
        )
        self.comments_by_video = json.loads(
            (FIXTURE_ROOT / "comments.json").read_text(encoding="utf-8")
        )
        self.baseline_videos = {}
        for baseline in self.baseline_sets.values():
            for video_id in baseline["video_ids"]:
                self.baseline_videos[video_id] = {
                    "video_id": video_id,
                    "title": video_id,
                    "channel_id": baseline["channel_id"],
                    "channel_title": baseline["channel_id"],
                    "published_at": baseline["published_at"],
                    "duration": baseline["duration"],
                    "views": baseline["views"],
                    "public_comment_count": 0,
                    "source_language": "en",
                    "live_state": baseline["live_state"],
                }
        self.quota_ledger = {"actual_units": 0, "cache_hits": 0, "by_resource": {}}
        self.search_limits = []
        self.comment_limits = []

    def search(self, query, published_after, max_results):
        self.search_limits.append(max_results)
        return self.searches[query][:max_results]

    def video_details(self, video_ids):
        all_videos = self.candidates | self.baseline_videos
        return [all_videos[video_id] for video_id in video_ids]

    def channel_details(self, channel_ids):
        return [self.channels_by_id[channel_id] for channel_id in channel_ids]

    def channel_uploads(self, channel_id, uploads_playlist_id, max_results):
        return self.baseline_sets[uploads_playlist_id]["video_ids"][:max_results]

    def comments(self, video_id, max_results, order, text_format):
        self.comment_limits.append(max_results)
        result = self.comments_by_video[video_id]
        return {"state": result["state"], "comments": result["comments"][:max_results]}


class QuotaAfterFirstGateway(FakeGateway):
    def comments(self, video_id, max_results, order, text_format):
        if video_id == "v2":
            raise YouTubeAPIError("quota_exhausted", "Quota exhausted")
        return super().comments(video_id, max_results, order, text_format)


def research_config():
    return ResearchConfig(
        research_name="AI beginners",
        queries=("AI for beginners", "ChatGPT for beginners"),
        target_language="English",
        min_duration_seconds=480,
        max_duration_seconds=1200,
        lookback_months=24,
        results_per_query=25,
        comments_per_video=100,
    )


def test_quota_estimate_is_an_upper_bound_for_five_queries():
    estimate = estimate_quota(5)
    assert estimate["search_units"] == 500
    assert estimate["upper_bound_units"] == 831
    assert estimate["candidate_upper_bound"] == 125


def test_redaction_never_exposes_api_key():
    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        "?part=snippet&key=secret-value&id=abc"
    )
    redacted = redact_url(url)
    assert "secret-value" not in redacted
    assert "key=REDACTED" in redacted


def test_canonical_key_ignores_parameter_order_and_secret():
    first = canonical_request_key(
        "videos", {"id": "abc", "part": "snippet", "key": "one"}
    )
    second = canonical_request_key(
        "videos", {"key": "two", "part": "snippet", "id": "abc"}
    )
    assert first == second


def test_cache_honors_freshness_without_overwriting_prior_payload(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    cache.put(
        "request", {"value": 1}, now, "videos", {"part": "snippet", "id": "abc"}
    )
    assert cache.get("request", 3600, now + timedelta(minutes=30)) == {"value": 1}
    assert cache.get("request", 3600, now + timedelta(hours=2)) is None


def test_api_key_prefers_environment_and_reads_gitignored_dotenv(tmp_path):
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=file-key\n", encoding="utf-8")
    assert load_api_key(tmp_path, {"YOUTUBE_API_KEY": "environment-key"}) == (
        "environment-key"
    )
    assert load_api_key(tmp_path, {}) == "file-key"


def test_collection_deduplicates_search_results_and_preserves_provenance():
    document = collect_evidence(research_config(), FakeGateway(), NOW)

    assert document["schema_version"] == "1.0"
    assert document["run"]["collection_status"] == "complete"
    assert len(document["evidence"]) == 2
    evidence = {item["video_id"]: item for item in document["evidence"]}
    assert evidence["v1"]["search_provenance"] == [
        "AI for beginners",
        "ChatGPT for beginners",
    ]
    assert evidence["v2"]["comments_state"] == "comments_disabled"
    assert evidence["v1"]["channel_subscriber_count"] == 1000
    assert evidence["v1"]["view_to_subscriber_ratio"] == 9.0
    assert {item["evidence_id"] for item in document["evidence"]} == {
        "yt-v1",
        "yt-v2",
    }
    allowed_comment_fields = {
        "comment_id",
        "text",
        "like_count",
        "published_at",
        "reply_count",
    }
    assert all(
        set(comment) <= allowed_comment_fields
        for item in document["evidence"]
        for comment in item["comments"]
    )


def test_collection_preserves_completed_items_after_quota_failure():
    document = collect_evidence(research_config(), QuotaAfterFirstGateway(), NOW)

    assert [item["evidence_id"] for item in document["evidence"]] == ["yt-v1"]
    assert document["run"]["collection_status"] == "partial"
    assert document["failures"][0]["state"] == "quota_exhausted"
    assert document["statuses"]["performance_status"] == "not_evaluable"


def test_collection_enforces_search_and_comment_caps():
    gateway = FakeGateway()
    oversized = replace(
        research_config(), results_per_query=99, comments_per_video=999
    )
    collect_evidence(oversized, gateway, NOW)
    assert gateway.search_limits == [25, 25]
    assert gateway.comment_limits == [100, 100]


def test_client_rejects_resources_outside_read_only_allowlist(tmp_path):
    client = YouTubeAPIClient("not-a-real-key", ResponseCache(tmp_path / "cache.db"))
    with pytest.raises(ValueError, match="Unsupported read-only resource"):
        client.get("subscriptions", {})


def test_client_maps_api_errors_without_exposing_key(tmp_path, monkeypatch):
    def fail(request, timeout):
        payload = {
            "error": {"errors": [{"reason": "quotaExceeded"}], "message": "stop"}
        }
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            BytesIO(json.dumps(payload).encode("utf-8")),
        )

    monkeypatch.setattr(collect_module, "urlopen", fail)
    client = YouTubeAPIClient("not-a-real-key", ResponseCache(tmp_path / "cache.db"))
    with pytest.raises(YouTubeAPIError) as error:
        client.get("videos", {"part": "snippet", "id": "v1"})
    assert error.value.state == "quota_exhausted"
    assert "not-a-real-key" not in str(error.value)


def test_client_cache_hits_consume_no_additional_units(tmp_path, monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'{"items": []}'

    def open_once(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(collect_module, "urlopen", open_once)
    cache = ResponseCache(tmp_path / "cache.db")
    client = YouTubeAPIClient("not-a-real-key", cache, now=lambda: NOW)
    params = {"part": "snippet", "id": "v1"}
    assert client.get("videos", params) == {"items": []}
    assert client.get("videos", params) == {"items": []}
    assert len(calls) == 1
    assert client.quota_ledger["actual_units"] == 1
    assert client.quota_ledger["cache_hits"] == 1
    with sqlite3.connect(cache.path) as connection:
        params_json = connection.execute(
            "SELECT params_json FROM responses"
        ).fetchone()[0]
    assert "not-a-real-key" not in params_json


def test_write_run_is_immutable(tmp_path):
    document = collect_evidence(research_config(), FakeGateway(), NOW)
    run_directory = write_run(document, tmp_path, "ai-beginners")
    assert json.loads((run_directory / "evidence.json").read_text(encoding="utf-8"))[
        "schema_version"
    ] == "1.0"
    with pytest.raises(FileExistsError):
        write_run(document, tmp_path, "ai-beginners")


def test_cli_estimate_and_confirmation_gate(capsys):
    assert main(["estimate", "--queries", "5"]) == 0
    estimate_output = json.loads(capsys.readouterr().out)
    assert estimate_output["upper_bound_units"] == 831

    assert main(["run"]) == 2
    assert (
        "Live collection requires explicit confirmation after quota review."
        in capsys.readouterr().err
    )
