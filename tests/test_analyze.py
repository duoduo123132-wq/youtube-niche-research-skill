from datetime import datetime, timezone

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


def test_comment_cleaning_removes_links_promotions_and_duplicates():
    comments = [
        {"comment_id": "1", "text": "I need a slower ChatGPT tutorial for beginners"},
        {"comment_id": "2", "text": "I need a slower ChatGPT tutorial for beginners"},
        {
            "comment_id": "3",
            "text": "Guaranteed returns https://spam.example WhatsApp me",
        },
        {"comment_id": "4", "text": "How can I use AI at work without coding?"},
    ]
    cleaned = clean_comments(comments)
    assert [item["comment_id"] for item in cleaned] == ["1", "4"]
    phrases = {item["phrase"] for item in extract_phrases(cleaned)}
    assert "chatgpt tutorial" in phrases
    assert all("http" not in phrase for phrase in phrases)


def test_comment_cleaning_removes_contact_handle_solicitation():
    comments = [{"comment_id": "1", "text": "DM @promo_account for details"}]
    assert clean_comments(comments) == []


def test_comment_evidence_is_independent_and_requires_clean_material():
    assert (
        comment_evidence_state(
            {
                "public_comment_count": 80,
                "fetched_comment_count": 80,
                "cleaned_comment_count": 60,
                "comments_state": "available",
            }
        )
        is True
    )
    assert (
        comment_evidence_state(
            {
                "public_comment_count": 80,
                "fetched_comment_count": 0,
                "cleaned_comment_count": 0,
                "comments_state": "disabled",
            }
        )
        is False
    )


def test_project_status_caps_each_channel_at_three_coverage_items():
    items = []
    for index in range(36):
        channel = "dominant" if index < 12 else f"channel-{index}"
        items.append(
            {
                "channel_id": channel,
                "qualified_performance": True,
                "strong_signal": index < 5,
                "audience_demand": index < 5,
                "cleaned_comment_count": 50 if index < 5 else 0,
                "recurring_need_phrases": ["ai for beginners"] if index < 5 else [],
            }
        )
    result = project_status(items)
    assert result["coverage_status"] == "insufficient"
    assert result["coverage_count"] == 27


def test_project_status_separates_coverage_performance_and_audience():
    items = []
    for index in range(30):
        items.append(
            {
                "channel_id": f"channel-{index // 3}",
                "qualified_performance": True,
                "strong_signal": index < 5,
                "audience_demand": index < 5,
                "cleaned_comment_count": 50 if index < 5 else 0,
                "recurring_need_phrases": ["ai for beginners"] if index < 5 else [],
            }
        )
    assert project_status(items) == {
        "coverage_status": "sufficient",
        "performance_status": "strong_signals_found",
        "audience_status": "recurring_needs_found",
        "qualified_count": 30,
        "coverage_count": 30,
        "distinct_channel_count": 10,
        "strong_signal_count": 5,
        "audience_video_count": 5,
        "cleaned_comment_count": 250,
    }
