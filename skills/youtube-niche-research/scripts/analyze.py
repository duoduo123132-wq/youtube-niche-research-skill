import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime


_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_LANGUAGE_NAMES = {"english": "en", "chinese": "zh", "中文": "zh", "英文": "en"}
_TOKEN = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
_SPAM = re.compile(
    r"https?://|www\.|\b(?:whatsapp|telegram)\b|"
    r"\bguaranteed\s+(?:returns?|profits?|income)\b|"
    r"\b(?:contact|message|dm|email)\s+me\b|"
    r"@[a-z0-9_]{2,}|"
    r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "mine",
    "my",
    "of",
    "on",
    "or",
    "our",
    "ours",
    "she",
    "should",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "they",
    "this",
    "those",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "without",
    "would",
    "you",
    "your",
    "yours",
}


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_duration(value: str) -> int:
    match = _DURATION.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid ISO-8601 duration: {value}")
    parts = {key: int(number or 0) for key, number in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _age_days(published_at: str, retrieved_at: datetime) -> float:
    return max((retrieved_at - _utc(published_at)).total_seconds() / 86400, 1.0)


def calculate_video_metrics(
    candidate: dict, baseline: list[dict], retrieved_at: datetime
) -> dict:
    if not baseline:
        raise ValueError("A non-empty baseline is required")
    median_views = statistics.median(int(item["views"]) for item in baseline)
    velocities = [
        int(item["views"]) / _age_days(item["published_at"], retrieved_at)
        for item in baseline
    ]
    median_velocity = statistics.median(velocities)
    candidate_age = _age_days(candidate["published_at"], retrieved_at)
    candidate_velocity = int(candidate["views"]) / candidate_age
    return {
        "age_days": round(candidate_age, 4),
        "view_velocity": round(candidate_velocity, 4),
        "channel_median_views": float(median_views),
        "channel_median_view_velocity": round(median_velocity, 4),
        "raw_outlier_multiple": (
            round(int(candidate["views"]) / median_views, 4) if median_views else None
        ),
        "age_adjusted_outlier_multiple": (
            round(candidate_velocity / median_velocity, 4)
            if median_velocity
            else None
        ),
    }


def metadata_language_match(source_language: str | None, target_language: str) -> str:
    if not source_language:
        return "unknown"
    target = _LANGUAGE_NAMES.get(
        target_language.lower(), target_language.lower()
    ).split("-")[0]
    source = source_language.lower().split("-")[0]
    return "high" if source == target else "low"


def is_qualified_video(item: dict, config: dict) -> bool:
    return all(
        (
            _utc(item["published_at"]) >= _utc(config["published_after"]),
            config["min_duration_seconds"]
            <= item["duration_seconds"]
            <= config["max_duration_seconds"],
            item["live_state"] == "none",
            item["language_match"] in {"high", "unknown"},
            item["baseline_count"] >= 10,
        )
    )


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def clean_comments(comments: list[dict]) -> list[dict]:
    cleaned = []
    seen = set()
    for item in comments:
        text = _normalize_text(str(item.get("text", "")))
        identity = text.casefold()
        if not text or identity in seen or _SPAM.search(text):
            continue
        seen.add(identity)
        normalized_item = dict(item)
        normalized_item["text"] = text
        cleaned.append(normalized_item)
    return cleaned


def extract_phrases(comments: list[dict], limit: int = 20) -> list[dict]:
    counts = Counter()
    comment_ids = defaultdict(set)
    for item in comments:
        tokens = [
            token.casefold()
            for token in _TOKEN.findall(str(item.get("text", "")))
            if token.casefold() not in _STOP_WORDS
        ]
        for size in range(2, 5):
            for start in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[start : start + size])
                counts[phrase] += 1
                if item.get("comment_id") is not None:
                    comment_ids[phrase].add(str(item["comment_id"]))

    ranked = sorted(
        counts,
        key=lambda phrase: (-counts[phrase], -len(phrase.split()), phrase),
    )[: max(limit, 0)]
    return [
        {
            "phrase": phrase,
            "count": counts[phrase],
            "comment_ids": sorted(comment_ids[phrase]),
        }
        for phrase in ranked
    ]


def comment_evidence_state(item: dict) -> bool:
    return all(
        (
            item.get("comments_state") == "available",
            item.get("public_comment_count", 0) >= 50,
            item.get("fetched_comment_count", 0) >= 50,
            item.get("cleaned_comment_count", 0) >= 50,
        )
    )


def project_status(items: list[dict]) -> dict:
    qualified = [item for item in items if item.get("qualified_performance")]
    ordered = sorted(
        qualified,
        key=lambda item: item.get("age_adjusted_outlier_multiple") or 0,
        reverse=True,
    )

    channel_counts = Counter()
    coverage_count = 0
    for item in ordered:
        channel_id = item["channel_id"]
        if channel_counts[channel_id] < 3:
            channel_counts[channel_id] += 1
            coverage_count += 1

    distinct_channel_count = len({item["channel_id"] for item in qualified})
    strong_signal_count = sum(bool(item.get("strong_signal")) for item in qualified)
    audience_items = [item for item in qualified if item.get("audience_demand")]
    audience_video_count = len(audience_items)
    cleaned_comment_count = sum(
        int(item.get("cleaned_comment_count", 0)) for item in audience_items
    )
    recurring_need_phrases = {
        phrase
        for item in audience_items
        for phrase in item.get("recurring_need_phrases", [])
    }

    coverage_status = (
        "sufficient"
        if coverage_count >= 30 and distinct_channel_count >= 8
        else "insufficient"
    )
    performance_status = (
        "not_evaluable"
        if coverage_status == "insufficient"
        else "strong_signals_found"
        if strong_signal_count >= 5
        else "no_strong_signal_in_sample"
    )
    audience_ready = audience_video_count >= 5 and cleaned_comment_count >= 250
    audience_status = (
        "not_evaluable"
        if not audience_ready
        else "recurring_needs_found"
        if recurring_need_phrases
        else "no_recurring_need_in_sample"
    )

    return {
        "coverage_status": coverage_status,
        "performance_status": performance_status,
        "audience_status": audience_status,
        "qualified_count": len(qualified),
        "coverage_count": coverage_count,
        "distinct_channel_count": distinct_channel_count,
        "strong_signal_count": strong_signal_count,
        "audience_video_count": audience_video_count,
        "cleaned_comment_count": cleaned_comment_count,
    }
