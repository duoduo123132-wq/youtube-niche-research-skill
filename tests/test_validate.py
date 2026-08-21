import csv
import json

import pytest

from validate import (
    CSV_FIELDS,
    REQUIRED_HEADINGS,
    validate_evidence,
    validate_report,
    main,
    write_topics_csv,
)


def valid_document():
    return {
        "schema_version": "1.0",
        "run": {
            "research_name": "AI beginners",
            "queries": ["AI for beginners"],
            "target_language": "English",
            "lookback_months": 24,
            "retrieved_at": "2026-08-20T00:00:00+00:00",
            "collection_status": "complete",
            "quota": {"actual_units": 0},
            "per_query_candidate_counts": {"AI for beginners": 1},
        },
        "statuses": {
            "coverage_status": "insufficient",
            "performance_status": "not_evaluable",
            "audience_status": "not_evaluable",
            "qualified_count": 1,
            "coverage_count": 1,
            "distinct_channel_count": 1,
            "strong_signal_count": 1,
            "audience_video_count": 0,
            "cleaned_comment_count": 0,
        },
        "evidence": [
            {
                "evidence_id": "yt-v1",
                "video_id": "v1",
                "title": "AI for Complete Beginners",
                "channel_id": "c1",
                "published_at": "2026-08-10T00:00:00Z",
                "duration_seconds": 600,
                "views": 9000,
                "baseline_count": 10,
                "qualified_performance": True,
                "strong_signal": True,
                "comments_state": "comments_disabled",
                "search_provenance": ["AI for beginners"],
            }
        ],
        "topics": [
            {
                "english_title": "AI for absolute beginners",
                "chinese_title": "零基础人工智能入门",
                "evidence_ids": ["yt-v1"],
            }
        ],
        "failures": [],
    }


def valid_report():
    sections = ["# YouTube 赛道研究"]
    for heading in REQUIRED_HEADINGS:
        sections.extend((f"## {heading}", "当前结论仅适用于本次样本。[yt-v1]"))
    sections.append(
        "- English title: AI for Complete Beginners；中文：人工智能零基础入门 [yt-v1]"
    )
    return "\n\n".join(sections) + "\n"


def test_topic_without_current_run_evidence_is_rejected(tmp_path):
    topics = [
        {
            "english_title": "AI for absolute beginners",
            "chinese_title": "零基础人工智能入门",
            "evidence_ids": ["yt-missing"],
        }
    ]
    with pytest.raises(ValueError, match="unknown evidence ID"):
        write_topics_csv(topics, {"yt-v1"}, tmp_path / "topics.csv")


def test_report_rejects_whole_market_claims():
    report = "# Report\n## 研究参数\n这个赛道已经验证可行。\n"
    errors = validate_report(report, {"yt-v1"})
    assert any("whole-market claim" in error for error in errors)


def test_evidence_rejects_secret_fields():
    document = {
        "schema_version": "1.0",
        "run": {"api_key": "secret"},
        "statuses": {},
        "evidence": [],
    }
    assert "secret-bearing field: run.api_key" in validate_evidence(document)


def test_evidence_rejects_missing_top_level_duplicate_ids_and_cross_run_topic():
    document = valid_document()
    document.pop("failures")
    document["evidence"].append(dict(document["evidence"][0]))
    document["topics"][0]["evidence_ids"] = ["yt-other-run"]
    errors = validate_evidence(document)
    assert "missing top-level field: failures" in errors
    assert "duplicate evidence ID" in errors
    assert any("unknown evidence ID" in error for error in errors)


def test_evidence_rejects_commenter_identity():
    document = valid_document()
    document["evidence"][0]["comments"] = [
        {"comment_id": "cm1", "text": "Useful", "author_display_name": "private"}
    ]
    assert any(
        "commenter identity field" in error for error in validate_evidence(document)
    )


def test_valid_evidence_and_bilingual_report_pass():
    assert validate_evidence(valid_document()) == []
    assert validate_report(valid_report(), {"yt-v1"}) == []


def test_report_rejects_unknown_citation_and_untranslated_english_title():
    report = valid_report().replace("；中文：人工智能零基础入门", "").replace(
        "[yt-v1]", "[yt-missing]"
    )
    errors = validate_report(report, {"yt-v1"})
    assert any("unknown evidence ID" in error for error in errors)
    assert any("Chinese explanation" in error for error in errors)


def test_report_rejects_each_uncited_insight_in_evidence_sections():
    report = valid_report().replace(
        "## 候选选题",
        "## 候选选题\n\n- 新手需要更慢的操作教程",
    )
    errors = validate_report(report, {"yt-v1"})
    assert any("missing evidence citation" in error for error in errors)


def test_untranslated_english_title_is_rejected_without_a_citation():
    report = valid_report() + "\nEnglish title: Untranslated title\n"
    errors = validate_report(report, {"yt-v1"})
    assert any("Chinese explanation" in error for error in errors)


def test_nested_heading_does_not_bypass_parent_section_citation_rule():
    report = valid_report().replace(
        "## 候选选题",
        "## 候选选题\n\n### 新手方向\n\n- 这是一条没有证据引用的候选选题",
    )
    errors = validate_report(report, {"yt-v1"})
    assert any("missing evidence citation" in error for error in errors)


def test_topics_csv_has_exact_columns_and_deterministic_evidence_ids(tmp_path):
    topics = [
        {
            "english_title": "AI for absolute beginners",
            "chinese_title": "零基础人工智能入门",
            "target_audience": "技术小白",
            "audience_need": "慢速讲解",
            "angle": "从第一个提示词开始",
            "evidence_ids": ["yt-v2", "yt-v1"],
            "sample_status": "初筛样本",
        }
    ]
    destination = tmp_path / "topics.csv"
    write_topics_csv(topics, {"yt-v1", "yt-v2"}, destination)

    with destination.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
    assert tuple(reader.fieldnames) == CSV_FIELDS
    assert rows[0]["evidence_ids"] == "yt-v1;yt-v2"


def test_cli_validates_complete_run_directory(tmp_path, capsys):
    (tmp_path / "evidence.json").write_text(
        json.dumps(valid_document(), ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "report.md").write_text(valid_report(), encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert "Research artifacts are valid." in capsys.readouterr().out
