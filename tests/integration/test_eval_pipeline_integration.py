"""Integration tests: EvalRunner pipeline with real SQL validation.

Uses a mock agent that returns pre-written SQL strings, then runs them
through SqlGuard (real) and sqlglot (real) — no LLM needed.
The DuckDB executor validates that the SQL is actually executable.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import yaml

from evaluation.eval_runner import EvalRunner, _is_sql_valid, _jaccard
from ai_data_agent.text2sql.sql_guard import SqlGuard, SqlGuardConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def guard() -> SqlGuard:
    return SqlGuard.from_config(SqlGuardConfig(require_time_filter=False))


@pytest.fixture()
def questions_yaml(tmp_path: Path) -> Path:
    data = {
        "questions": [
            {
                "id": "int_q001",
                "domain": "drug",
                "difficulty": "easy",
                "question": "统计本月肿瘤内科抗肿瘤药物使用总金额",
                "expected_tables": ["dwd.dwd_order", "dim.dim_drug_dict", "dim.dim_dept_dict"],
                "expected_metrics": ["antitumor_drug_amount"],
                "expected_fields": ["dept_code", "drug_expense"],
            },
            {
                "id": "int_q002",
                "domain": "patient",
                "difficulty": "medium",
                "question": "统计本月肺癌住院患者人数",
                "expected_tables": ["dwd.dwd_visit", "dwd.dwd_diagnosis", "dim.dim_diagnosis_dict"],
                "expected_metrics": ["patient_count"],
                "expected_fields": ["mpi_id", "tumor_type"],
            },
            {
                "id": "int_q003",
                "domain": "dq",
                "difficulty": "easy",
                "question": "本周DQ问题最多的表",
                "expected_tables": ["ads.ads_dq_result_summary"],
                "expected_metrics": ["dq_issue_count"],
                "expected_fields": ["table_name"],
            },
        ]
    }
    path = tmp_path / "int_questions.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture()
def runner(questions_yaml: Path) -> EvalRunner:
    return EvalRunner(questions_path=questions_yaml)


# ---------------------------------------------------------------------------
# Agent stubs
# ---------------------------------------------------------------------------

_PERFECT_SQLS = {
    "int_q001": (
        "SELECT o.dept_code, SUM(o.drug_expense) AS total_expense "
        "FROM dwd.dwd_order AS o "
        "JOIN dim.dim_drug_dict AS dd ON o.drug_code = dd.drug_code "
        "JOIN dim.dim_dept_dict AS dep ON o.dept_code = dep.dept_code "
        "WHERE dd.is_antitumor = true "
        "AND o.order_status = 'COMPLETED' "
        "AND o.order_date >= '2025-01-01' "
        "GROUP BY o.dept_code "
        "LIMIT 20"
    ),
    "int_q002": (
        "SELECT COUNT(DISTINCT v.mpi_id) AS patient_count "
        "FROM dwd.dwd_visit AS v "
        "JOIN dwd.dwd_diagnosis AS d ON v.visit_id = d.visit_id "
        "JOIN dim.dim_diagnosis_dict AS dd ON d.diagnosis_code = dd.icd_code "
        "WHERE dd.tumor_type = 'lung' "
        "AND v.visit_type = '住院' "
        "AND v.visit_date >= '2025-01-01' "
        "LIMIT 1"
    ),
    "int_q003": (
        "SELECT table_name, SUM(issue_count) AS total_issues "
        "FROM ads.ads_dq_result_summary "
        "WHERE stat_date >= '2025-01-01' "
        "GROUP BY table_name "
        "ORDER BY total_issues DESC "
        "LIMIT 10"
    ),
}


def _stateful_agent(sqls: dict[str, str]):
    """Factory: agent that returns the right SQL for each question id."""
    ids: list[str] = []

    def agent_fn(question: str) -> dict:
        # EvalRunner passes the question text; map back by index
        idx = len(ids)
        ids.append(question)
        sql_values = list(sqls.values())
        sql = sql_values[idx] if idx < len(sql_values) else ""
        return {"sql": sql}

    return agent_fn


def _broken_agent(question: str) -> dict:
    return {"sql": "THIS IS NOT SQL"}


def _sensitive_agent(question: str) -> dict:
    return {
        "sql": (
            "SELECT patient_name, id_card FROM dwd.dwd_patient "
            "WHERE etl_date = '2025-01-01' LIMIT 10"
        )
    }


# ---------------------------------------------------------------------------
# EvalRunner integration tests
# ---------------------------------------------------------------------------


def test_eval_all_questions_pass_with_perfect_agent(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    agent = _stateful_agent(_PERFECT_SQLS)
    report = runner.run(questions, agent)

    assert report.summary.total == 3
    assert report.summary.sql_valid_rate == 1.0
    assert report.summary.sql_safe_rate == 1.0


def test_eval_table_match_rate_with_perfect_agent(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    agent = _stateful_agent(_PERFECT_SQLS)
    report = runner.run(questions, agent)

    # All SQLs reference the expected tables
    for qr in report.question_results:
        assert qr.table_jaccard > 0.0, f"{qr.question_id} table_jaccard should be > 0"


def test_eval_broken_agent_fails_all(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    report = runner.run(questions, _broken_agent)

    assert report.summary.sql_valid_rate == 0.0
    assert report.summary.sql_safe_rate == 0.0


def test_eval_sensitive_agent_fails_safety(runner: EvalRunner) -> None:
    questions = runner.load_questions()[:1]
    report = runner.run(questions, _sensitive_agent)

    assert report.question_results[0].sql_safe is False
    assert report.question_results[0].sql_valid is True  # valid SQL, just unsafe


def test_eval_report_to_markdown(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    agent = _stateful_agent(_PERFECT_SQLS)
    report = runner.run(questions, agent)
    md = report.to_markdown()

    assert "## Summary" in md
    assert "int_q001" in md or "drug" in md


def test_eval_report_to_json_structure(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    agent = _stateful_agent(_PERFECT_SQLS)
    report = runner.run(questions, agent)
    data = report.to_json()

    assert data["summary"]["total"] == 3
    assert len(data["results"]) == 3


def test_eval_by_domain_grouping(runner: EvalRunner) -> None:
    questions = runner.load_questions()
    agent = _stateful_agent(_PERFECT_SQLS)
    report = runner.run(questions, agent)

    assert "drug" in report.summary.by_domain
    assert "patient" in report.summary.by_domain
    assert "dq" in report.summary.by_domain


# ---------------------------------------------------------------------------
# SQL executability against real DuckDB
# ---------------------------------------------------------------------------


def test_perfect_sqls_are_executable(medical_db: duckdb.DuckDBPyConnection) -> None:
    """Every pre-written SQL must actually execute on the test database."""
    for qid, sql in _PERFECT_SQLS.items():
        try:
            rows = medical_db.execute(sql).fetchall()
            assert rows is not None, f"{qid}: query returned None"
        except Exception as exc:
            pytest.fail(f"{qid} SQL execution failed: {exc}\nSQL: {sql}")


def test_lung_cancer_inpatient_sql_returns_correct_count(
    medical_db: duckdb.DuckDBPyConnection,
) -> None:
    sql = _PERFECT_SQLS["int_q002"]
    result = medical_db.execute(sql).fetchone()
    # V001 (P001, 住院, C34.1 lung) — only one lung cancer inpatient
    assert result[0] == 1


def test_drug_expense_sql_returns_correct_total(
    medical_db: duckdb.DuckDBPyConnection,
) -> None:
    sql = _PERFECT_SQLS["int_q001"]
    rows = medical_db.execute(sql).fetchall()
    assert len(rows) >= 1
    total = float(rows[0][1])
    # O001(3200) + O002(1800) + O003(2400) + O004(3200) = 10600 (O006 not antitumor)
    assert total == pytest.approx(10600.0)
