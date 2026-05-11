"""Tests for the batch evaluation runner."""

from __future__ import annotations

import json
from pathlib import Path

from ai_data_agent.evaluation.runner import (
    EvalQuestion,
    build_report,
    evaluate_question,
    load_questions,
)

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "evaluation" / "questions.jsonl"


def test_load_questions_returns_20_records() -> None:
    questions = load_questions(QUESTIONS_PATH)
    assert len(questions) >= 20
    assert questions[0].id == "q001"


def test_load_questions_preserves_expected_tables() -> None:
    questions = load_questions(QUESTIONS_PATH)
    q001 = questions[0]
    assert "dws.dws_tumor_drug_usage_1d" in q001.expected_tables


def test_evaluate_question_passes_when_tables_match() -> None:
    question = EvalQuestion(
        id="test-1", domain="drug", question="test",
        expected_tables=["dws.dws_tumor_drug_usage_1d", "dim.dim_dept_dict"],
    )
    result = evaluate_question(
        question=question,
        sql="SELECT * FROM dws.dws_tumor_drug_usage_1d JOIN dim.dim_dept_dict ON ... LIMIT 10",
        context_tables=["dws.dws_tumor_drug_usage_1d", "dim.dim_dept_dict"],
        context_metrics=[],
        context_dq_rules=[],
        elapsed_ms=100,
    )
    assert result.passed is True
    assert result.checks["tables_in_sql"] is True


def test_evaluate_question_fails_when_table_missing() -> None:
    question = EvalQuestion(
        id="test-2", domain="drug", question="test",
        expected_tables=["dws.dws_tumor_drug_usage_1d", "dim.dim_dept_dict"],
    )
    result = evaluate_question(
        question=question,
        sql="SELECT * FROM dws.dws_tumor_drug_usage_1d LIMIT 10",
        context_tables=["dws.dws_tumor_drug_usage_1d"],
        context_metrics=[],
        context_dq_rules=[],
        elapsed_ms=100,
    )
    assert result.passed is False
    assert result.checks["tables_in_sql"] is False
    assert "dim.dim_dept_dict" in result.details["tables_missing"]


def test_evaluate_question_passes_metrics_in_context() -> None:
    question = EvalQuestion(
        id="test-3", domain="drug", question="test",
        expected_metrics=["antitumor_drug_amount"],
    )
    result = evaluate_question(
        question=question,
        sql="SELECT * FROM dws.dws_tumor_drug_usage_1d LIMIT 10",
        context_tables=[],
        context_metrics=["antitumor_drug_amount"],
        context_dq_rules=[],
        elapsed_ms=100,
    )
    assert result.checks["metrics_in_context"] is True


def test_evaluate_question_handles_pipeline_error() -> None:
    question = EvalQuestion(id="test-4", domain="dq", question="test")
    result = evaluate_question(
        question=question,
        sql="",
        context_tables=[],
        context_metrics=[],
        context_dq_rules=[],
        elapsed_ms=50,
        error="Connection refused",
    )
    assert result.passed is False
    assert result.error == "Connection refused"


def test_evaluate_question_passes_dq_rules() -> None:
    question = EvalQuestion(
        id="test-5", domain="dq", question="test",
        expected_dq_rules=["DQ-001"],
    )
    result = evaluate_question(
        question=question,
        sql="SELECT * FROM dq.dq_check_result LIMIT 10",
        context_tables=[],
        context_metrics=[],
        context_dq_rules=["DQ-001", "DQ-002"],
        elapsed_ms=100,
    )
    assert result.checks["dq_rules_in_context"] is True


def test_evaluate_question_passes_dimensions() -> None:
    question = EvalQuestion(
        id="test-6", domain="expense", question="test",
        expected_dimensions=["dept_code", "dept_name"],
    )
    result = evaluate_question(
        question=question,
        sql="SELECT dept_code, dept_name FROM dws.dws_expense_summary_1d LIMIT 10",
        context_tables=[],
        context_metrics=[],
        context_dq_rules=[],
        elapsed_ms=100,
    )
    assert result.checks["dimensions_in_sql"] is True


def test_evaluate_question_no_checks_passes() -> None:
    question = EvalQuestion(id="test-7", domain="misc", question="generic question")
    result = evaluate_question(
        question=question,
        sql="SELECT 1 LIMIT 1",
        context_tables=[],
        context_metrics=[],
        context_dq_rules=[],
        elapsed_ms=10,
    )
    assert result.passed is True


def test_build_report_summary() -> None:
    q1 = EvalQuestion(id="q1", domain="drug", question="q1", expected_tables=["dws.t1"])
    q2 = EvalQuestion(id="q2", domain="dq", question="q2")
    results = [
        evaluate_question(q1, "SELECT * FROM dws.t1 LIMIT 10", ["dws.t1"], [], [], 100),
        evaluate_question(q2, "SELECT 1 LIMIT 1", [], [], [], 50),
    ]
    report = build_report(results)
    assert report.total == 2
    assert report.passed == 2
    assert report.pass_rate == 1.0
    assert report.domain_summary["drug"]["passed"] == 1
    assert report.domain_summary["dq"]["passed"] == 1
    assert "q1" in report.summary_table()


def test_build_report_counts_failures() -> None:
    q1 = EvalQuestion(id="q1", domain="drug", question="q1", expected_tables=["dws.missing"])
    results = [
        evaluate_question(q1, "SELECT * FROM dws.other LIMIT 10", [], [], [], 100),
    ]
    report = build_report(results)
    assert report.total == 1
    assert report.failed == 1
    assert report.pass_rate == 0.0


def test_report_to_dict_serializable() -> None:
    q1 = EvalQuestion(id="q1", domain="drug", question="q1")
    results = [evaluate_question(q1, "SELECT 1 LIMIT 1", [], [], [], 10)]
    report = build_report(results)
    serialized = json.dumps(report.to_dict(), ensure_ascii=False)
    assert "q1" in serialized
