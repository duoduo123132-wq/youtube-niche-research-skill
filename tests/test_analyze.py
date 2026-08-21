from datetime import datetime, timezone

from analyze import (
    calculate_video_metrics,
    is_qualified_video,
    metadata_language_match,
    parse_duration,
)


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_parse_iso_duration():
    assert parse_duration("PT12M5S") == 725
    assert parse_duration("PT1H2M3S") == 3723


def test_age_adjusted_outlier_uses_view_velocity():
    candidate = {"views": 9000, "published_at": "2026-08-10T00:00:00Z"}
    baseline = [
        {"views": 1000, "published_at": "2026-08-10T00:00:00Z"},
        {"views": 2000, "published_at": "2026-07-31T00:00:00Z"},
        {"views": 3000, "published_at": "2026-07-21T00:00:00Z"},
    ]
    metrics = calculate_video_metrics(candidate, baseline, NOW)
    assert metrics["raw_outlier_multiple"] == 4.5
    assert metrics["age_adjusted_outlier_multiple"] == 9.0
    assert metrics["age_days"] == 10.0


def test_language_metadata_is_three_state():
    assert metadata_language_match("en-US", "English") == "high"
    assert metadata_language_match("de", "English") == "low"
    assert metadata_language_match(None, "English") == "unknown"


def test_comments_are_not_required_for_performance_qualification():
    item = {
        "published_at": "2026-08-01T00:00:00Z",
        "duration_seconds": 600,
        "live_state": "none",
        "language_match": "high",
        "baseline_count": 12,
        "comments_state": "disabled",
    }
    config = {
        "published_after": "2024-08-20T00:00:00Z",
        "min_duration_seconds": 480,
        "max_duration_seconds": 1200,
    }
    assert is_qualified_video(item, config) is True
