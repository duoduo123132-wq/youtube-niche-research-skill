import argparse
import csv
import json
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = (
    "研究参数与采集状态",
    "搜索范围与局限",
    "样本覆盖、播放信号与观众需求",
    "最强证据",
    "子方向",
    "观众需求与异议",
    "候选选题",
    "限制与下一步",
)
FORBIDDEN_CLAIMS = (
    "赛道已经验证可行",
    "赛道不可行",
    "一定能成功",
    "no opportunity exists",
    "the niche is viable",
    "the niche is not viable",
)
CSV_FIELDS = (
    "english_title",
    "chinese_title",
    "target_audience",
    "audience_need",
    "angle",
    "evidence_ids",
    "sample_status",
)
_SECRET_FIELDS = {
    "api_key",
    "youtube_api_key",
    "authorization",
    "access_token",
    "refresh_token",
}
_COMMENTER_IDENTITY_FIELDS = {
    "author",
    "author_display_name",
    "author_channel_id",
}
_RUN_FIELDS = {
    "research_name",
    "queries",
    "target_language",
    "lookback_months",
    "retrieved_at",
    "collection_status",
    "quota",
    "per_query_candidate_counts",
}
_STATUS_FIELDS = {
    "coverage_status",
    "performance_status",
    "audience_status",
    "qualified_count",
    "coverage_count",
    "distinct_channel_count",
    "strong_signal_count",
    "audience_video_count",
    "cleaned_comment_count",
}
_EVIDENCE_FIELDS = {
    "evidence_id",
    "video_id",
    "title",
    "channel_id",
    "published_at",
    "duration_seconds",
    "views",
    "baseline_count",
    "qualified_performance",
    "strong_signal",
    "comments_state",
    "search_provenance",
}
_CITATION = re.compile(r"\[(yt-[^\]\s]+)\]", re.IGNORECASE)
_CHINESE = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_ENGLISH_LABEL = re.compile(r"\benglish\s+(?:title|term)\s*:", re.IGNORECASE)
_QUOTED_ENGLISH = re.compile(
    r"`[^`]*[A-Za-z]{2,}[^`]*`|[\"“][^\"”]*[A-Za-z]{2,}[^\"”]*[\"”]"
)
_CITATION_REQUIRED_HEADINGS = {
    "最强证据",
    "子方向",
    "观众需求与异议",
    "候选选题",
}


def _field_paths(value, path=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            current = f"{path}.{key}" if path else str(key)
            yield current, str(key).casefold()
            yield from _field_paths(nested, current)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            current = f"{path}[{index}]"
            yield from _field_paths(nested, current)


def _missing_fields(value: dict, required: set[str]) -> list[str]:
    return sorted(required - set(value))


def validate_evidence(document: dict) -> list[str]:
    errors = []
    for name in sorted({"run", "statuses", "evidence", "failures"} - set(document)):
        errors.append(f"missing top-level field: {name}")
    for path, normalized_key in _field_paths(document):
        if normalized_key in _SECRET_FIELDS:
            errors.append(f"secret-bearing field: {path}")
        if normalized_key in _COMMENTER_IDENTITY_FIELDS and ".comments[" in path:
            errors.append(f"commenter identity field: {path}")

    if document.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")

    run = document.get("run")
    if not isinstance(run, dict):
        errors.append("run must be an object")
    else:
        errors.extend(f"missing run field: {name}" for name in _missing_fields(run, _RUN_FIELDS))

    statuses = document.get("statuses")
    if not isinstance(statuses, dict):
        errors.append("statuses must be an object")
    else:
        errors.extend(
            f"missing status field: {name}"
            for name in _missing_fields(statuses, _STATUS_FIELDS)
        )

    evidence = document.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence must be an array")
        evidence = []

    evidence_ids = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        errors.extend(
            f"missing evidence field: evidence[{index}].{name}"
            for name in _missing_fields(item, _EVIDENCE_FIELDS)
        )
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            evidence_ids.append(evidence_id)
        else:
            errors.append(f"invalid evidence ID: evidence[{index}].evidence_id")

    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("duplicate evidence ID")

    known_ids = set(evidence_ids)
    topics = document.get("topics", [])
    if not isinstance(topics, list):
        errors.append("topics must be an array")
    else:
        for index, topic in enumerate(topics):
            if not isinstance(topic, dict):
                errors.append(f"topics[{index}] must be an object")
                continue
            references = topic.get("evidence_ids", [])
            if not references:
                errors.append(f"topics[{index}] has no evidence ID")
                continue
            for evidence_id in references:
                if evidence_id not in known_ids:
                    errors.append(
                        f"topics[{index}] references unknown evidence ID: {evidence_id}"
                    )
    return errors


def validate_report(markdown: str, evidence_ids: set[str]) -> list[str]:
    errors = []
    heading_lines = {
        match.group(1).strip()
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE)
    }
    for heading in REQUIRED_HEADINGS:
        if heading not in heading_lines:
            errors.append(f"missing report heading: {heading}")

    folded = markdown.casefold()
    for phrase in FORBIDDEN_CLAIMS:
        if phrase.casefold() in folded:
            errors.append(f"whole-market claim: {phrase}")

    citations = _CITATION.findall(markdown)
    for evidence_id in citations:
        if evidence_id not in evidence_ids:
            errors.append(f"unknown evidence ID in report: {evidence_id}")
    if evidence_ids and not citations:
        errors.append("report has no evidence citation")

    lines = markdown.splitlines()
    active_required_section = None
    for index, line in enumerate(lines):
        line_number = index + 1
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            heading_level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if heading_text in _CITATION_REQUIRED_HEADINGS:
                active_required_section = heading_text
            elif heading_level <= 2:
                active_required_section = None
            continue

        content = line.strip()
        if (
            active_required_section is not None
            and content
            and not content.startswith("```")
            and not _is_table_separator(content)
            and not _is_table_header(lines, index)
            and not _CITATION.search(content)
        ):
            errors.append(f"missing evidence citation on line {line_number}")

        text_without_citations = _CITATION.sub("", line)
        requires_chinese = bool(
            _ENGLISH_LABEL.search(line)
            or _QUOTED_ENGLISH.search(line)
            or (_CITATION.search(line) and _LATIN_WORD.search(text_without_citations))
        )
        if requires_chinese and not _CHINESE.search(line):
            errors.append(
                f"English title or term lacks Chinese explanation on line {line_number}"
            )
    return errors


def _is_table_separator(line: str) -> bool:
    return bool(line) and not re.sub(r"[|:\-\s]", "", line)


def _is_table_header(lines: list[str], index: int) -> bool:
    if not lines[index].lstrip().startswith("|"):
        return False
    for following in lines[index + 1 :]:
        if following.strip():
            return _is_table_separator(following.strip())
    return False


def write_topics_csv(
    topics: list[dict], evidence_ids: set[str], destination: Path
) -> None:
    rows = []
    for index, topic in enumerate(topics):
        references = topic.get("evidence_ids", [])
        if not references:
            raise ValueError(f"topic {index} has no evidence ID")
        unknown = sorted(set(references) - evidence_ids)
        if unknown:
            raise ValueError(f"topic {index} references unknown evidence ID: {unknown[0]}")
        if not topic.get("english_title") or not topic.get("chinese_title"):
            raise ValueError(f"topic {index} requires English and Chinese titles")
        row = {field: topic.get(field, "") for field in CSV_FIELDS}
        row["evidence_ids"] = ";".join(sorted(set(references)))
        rows.append(row)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_run_directory(run_directory: Path) -> list[str]:
    errors = []
    evidence_path = run_directory / "evidence.json"
    report_path = run_directory / "report.md"
    if not evidence_path.is_file():
        return ["missing evidence.json"]
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"invalid evidence.json: {error}"]
    errors.extend(validate_evidence(document))
    if not report_path.is_file():
        errors.append("missing report.md")
    else:
        try:
            markdown = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"invalid report.md: {error}")
        else:
            evidence_ids = {
                item.get("evidence_id")
                for item in document.get("evidence", [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
            errors.extend(validate_report(markdown, evidence_ids))
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate a YouTube research run")
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args(argv)
    errors = validate_run_directory(args.run_directory)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Research artifacts are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
