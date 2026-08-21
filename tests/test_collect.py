from datetime import datetime, timedelta, timezone

from collect import (
    ResponseCache,
    canonical_request_key,
    estimate_quota,
    load_api_key,
    redact_url,
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
