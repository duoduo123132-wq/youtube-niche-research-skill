import re
import statistics
from datetime import datetime


_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_LANGUAGE_NAMES = {"english": "en", "chinese": "zh", "中文": "zh", "英文": "en"}


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
