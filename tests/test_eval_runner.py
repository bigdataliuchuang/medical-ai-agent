"""Tests for EvalRunner (evaluation harness)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evaluation.eval_runner import (
    BenchmarkQuestion,
    EvalRunner,
    _jaccard,
    _is_sql_valid,
)


@pytest.fixture()
def questions_yaml(tmp_path: Path) -> Path:
    data = {
        "questions": [
            {
                "id": "q001",
                "domain": "drug",
                "difficulty": "easy",
                "question": "统计本月各科室抗肿瘤药物使用金额。",
                "expected_tables": ["dws.dws_tumor_drug_usage_1d", "dim.dim_dept_dict"],
                "expected_metrics": ["antitumor_drug_amount"],
                "expected_fields": ["dept_code"],
            },
            {
                "id": "q002",
                "domain": "dq",
                "difficulty": "medium",
                "question": "本周 DQ 问题最多的表有哪些？",
                "expected_tables": ["ads.ads_dq_result_summary"],
                "expected_metrics": ["dq_issue_count"],
                "expected_fields": ["table_name"],
            },
        ]
    }
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture()
def runner(questions_yaml: Path) -> EvalRunner:
    return EvalRunner(questions_path=questions_yaml)


def _perfect_agent(question: str) -> dict:
    return {
        "sql": (
            "SELECT dept_code, SUM(drug_expense_total) AS total "
            "FROM dws.dws_tumor_drug_usage_1d "
            "JOIN dim.dim_dept_dict USING (dept_code) "
            "WHERE stat_month = '2025-01' "
            "GROUP BY dept_code "
            "LIMIT 20"
        )
    }


def _broken_agent(question: str) -> dict:
    return {"sql": "NOT VALID SQL !!!"}


def _empty_agent(question: str) -> dict:
    return {"sql": ""}


def _error_agent(question: str) -> dict:
    raise RuntimeError("Agent crashed")


def test_load_questions(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    assert len(questions) == 2
    assert questions[0].id == "q001"
    assert questions[1].domain == "dq"


def test_run_with_valid_sql(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    report = runner.run(questions[:1], _perfect_agent)
    assert report.summary.total == 1
    assert report.summary.sql_valid_rate == 1.0
    assert report.summary.sql_safe_rate == 1.0


def test_run_with_broken_sql(runner: EvalRunner) -> None:
    questions = runner.load_questions()[:1]
    report = runner.run(questions, _broken_agent)
    assert report.summary.sql_valid_rate == 0.0
    assert report.summary.sql_safe_rate == 0.0


def test_run_with_empty_sql(runner: EvalRunner) -> None:
    questions = runner.load_questions()[:1]
    report = runner.run(questions, _empty_agent)
    assert report.question_results[0].sql_valid is False
    assert report.question_results[0].sql_safe is False


def test_run_handles_agent_exception(runner: EvalRunner) -> None:
    questions = runner.load_questions()[:1]
    report = runner.run(questions, _error_agent)
    assert report.question_results[0].error is not None
    assert report.question_results[0].sql_valid is False


def test_run_all_questions(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    report = runner.run(questions, _perfect_agent)
    assert report.summary.total == 2
    assert len(report.question_results) == 2


def test_report_has_eval_run_id(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions()[:1], _perfect_agent, eval_run_id="test_run")
    assert report.eval_run_id == "test_run"


def test_report_auto_generates_run_id(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions()[:1], _perfect_agent)
    assert len(report.eval_run_id) > 0


def test_to_markdown_contains_summary(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions(), _perfect_agent)
    md = report.to_markdown()
    assert "## Summary" in md
    assert "sql_valid_rate" in md.lower() or "SQL valid rate" in md


def test_to_json_structure(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions(), _perfect_agent)
    data = report.to_json()
    assert "summary" in data
    assert "results" in data
    assert data["summary"]["total"] == 2


def test_table_jaccard_perfect_match() -> None:
    score = _jaccard({"a", "b"}, {"a", "b"})
    assert score == 1.0


def test_table_jaccard_no_match() -> None:
    score = _jaccard({"a", "b"}, {"c", "d"})
    assert score == 0.0


def test_table_jaccard_partial_match() -> None:
    score = _jaccard({"a", "b", "c"}, {"a", "b", "d"})
    assert pytest.approx(score, rel=0.01) == 2 / 4


def test_is_sql_valid_with_good_sql() -> None:
    assert _is_sql_valid("SELECT 1 FROM ads.t WHERE stat_month='2025-01' LIMIT 1") is True


def test_is_sql_valid_with_bad_sql() -> None:
    assert _is_sql_valid("NOT SQL AT ALL !!!") is False


def test_is_sql_valid_with_empty() -> None:
    assert _is_sql_valid("") is False


def test_by_domain_grouping(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions(), _perfect_agent)
    assert "drug" in report.summary.by_domain
    assert "dq" in report.summary.by_domain


def test_by_difficulty_grouping(runner: EvalRunner) -> None:
    report = runner.run(runner.load_questions(), _perfect_agent)
    assert "easy" in report.summary.by_difficulty
    assert "medium" in report.summary.by_difficulty
