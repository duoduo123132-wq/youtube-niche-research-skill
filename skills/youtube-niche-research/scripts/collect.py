import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
