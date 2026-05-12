"""Integration tests: SqlGuard + DuckDB executor working together.

Validates that the guard correctly allows or rejects realistic medical SQL
before it reaches the database, and that allowed queries actually execute.
"""

from __future__ import annotations

import duckdb
import pytest

from ai_data_agent.executor.duckdb import DuckDBExecutor
from ai_data_agent.text2sql.sql_guard import SqlGuard, SqlGuardConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_MEDICAL_SCHEMAS = ("dwd", "dws", "ads", "dim")


@pytest.fixture()
def guard() -> SqlGuard:
    return SqlGuard(
        allowed_schemas=_MEDICAL_SCHEMAS,
        require_limit_for_detail_query=True,
        require_time_filter=False,
    )


@pytest.fixture()
def executor(medical_db: duckdb.DuckDBPyConnection, tmp_path) -> DuckDBExecutor:
    """DuckDB executor that writes to a temp file so DuckDBExecutor can open it."""
    import duckdb as _duckdb

    db_path = str(tmp_path / "medical_test.db")
    # Copy the in-memory DB to a file so DuckDBExecutor can connect
    conn = _duckdb.connect(db_path)
    # Re-create schema and data in the file DB
    from tests.integration.conftest import _DDL, _SEED

    conn.execute(_DDL)
    conn.execute(_SEED)
    conn.close()
    return DuckDBExecutor(database_path=db_path)


# ---------------------------------------------------------------------------
# Guard allows valid queries
# ---------------------------------------------------------------------------


def test_guard_allows_simple_select(guard: SqlGuard) -> None:
    sql = (
        "SELECT dept_code, SUM(drug_expense) AS total "
        "FROM dwd.dwd_order "
        "WHERE order_status = 'COMPLETED' "
        "GROUP BY dept_code "
        "LIMIT 20"
    )
    result = guard.validate(sql)
    assert result.allowed, result.reasons


def test_guard_allows_multi_table_join(guard: SqlGuard) -> None:
    sql = (
        "SELECT p.mpi_id, COUNT(d.diag_id) AS diag_count "
        "FROM dwd.dwd_patient AS p "
        "JOIN dwd.dwd_diagnosis AS d ON p.mpi_id = d.mpi_id "
        "WHERE p.etl_date >= '2025-01-01' "
        "GROUP BY p.mpi_id "
        "LIMIT 100"
    )
    result = guard.validate(sql)
    assert result.allowed, result.reasons


# ---------------------------------------------------------------------------
# Guard rejects dangerous queries
# ---------------------------------------------------------------------------


def test_guard_rejects_drop_table(guard: SqlGuard) -> None:
    result = guard.validate("DROP TABLE dwd.dwd_patient")
    assert not result.allowed
    assert result.risk_level == "HIGH"


def test_guard_rejects_delete(guard: SqlGuard) -> None:
    result = guard.validate("DELETE FROM dwd.dwd_order WHERE 1=1")
    assert not result.allowed


def test_guard_rejects_select_star(guard: SqlGuard) -> None:
    result = guard.validate("SELECT * FROM dwd.dwd_patient LIMIT 10")
    assert not result.allowed
    assert any("SELECT *" in r for r in result.reasons)


def test_guard_rejects_unqualified_table(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT mpi_id FROM dwd_patient LIMIT 10"
    )
    assert not result.allowed


def test_guard_rejects_missing_limit(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT mpi_id FROM dwd.dwd_patient WHERE etl_date = '2025-01-01'"
    )
    assert not result.allowed
    assert any("LIMIT" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Sensitive field detection
# ---------------------------------------------------------------------------


def test_guard_detects_id_card_field(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT mpi_id, id_card FROM dwd.dwd_patient WHERE etl_date='2025-01-01' LIMIT 10"
    )
    assert not result.allowed
    assert "id_card" in result.sensitive_fields


def test_guard_detects_phone_field(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT mpi_id, phone FROM dwd.dwd_patient WHERE etl_date='2025-01-01' LIMIT 10"
    )
    assert not result.allowed
    assert "phone" in result.sensitive_fields


def test_guard_detects_patient_name_field(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT patient_name, mpi_id FROM dwd.dwd_patient WHERE etl_date='2025-01-01' LIMIT 5"
    )
    assert not result.allowed
    assert "patient_name" in result.sensitive_fields


def test_guard_risk_level_high_for_sensitive(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT id_card FROM dwd.dwd_patient WHERE etl_date='2025-01-01' LIMIT 1"
    )
    assert result.risk_level in ("MEDIUM", "HIGH")


# ---------------------------------------------------------------------------
# Guard + Executor end-to-end pipeline
# ---------------------------------------------------------------------------


def test_guard_then_execute_lung_cancer_count(
    guard: SqlGuard, executor: DuckDBExecutor
) -> None:
    sql = (
        "SELECT COUNT(DISTINCT d.mpi_id) AS patient_count "
        "FROM dwd.dwd_diagnosis AS d "
        "JOIN dim.dim_diagnosis_dict AS dd ON d.diagnosis_code = dd.icd_code "
        "WHERE dd.tumor_type = 'lung' "
        "AND d.visit_date >= '2025-01-01' "
        "LIMIT 1"
    )
    guard_result = guard.validate(sql)
    assert guard_result.allowed, guard_result.reasons

    query_result = executor.execute(sql)
    assert query_result.row_count == 1
    assert query_result.rows[0]["patient_count"] == 2


def test_guard_then_execute_dept_expense(
    guard: SqlGuard, executor: DuckDBExecutor
) -> None:
    sql = (
        "SELECT o.dept_code, SUM(o.drug_expense) AS total_expense "
        "FROM dwd.dwd_order AS o "
        "JOIN dim.dim_drug_dict AS dd ON o.drug_code = dd.drug_code "
        "WHERE dd.is_antitumor = true "
        "AND o.order_status = 'COMPLETED' "
        "AND o.order_date >= '2025-01-01' "
        "GROUP BY o.dept_code "
        "ORDER BY total_expense DESC "
        "LIMIT 10"
    )
    guard_result = guard.validate(sql)
    assert guard_result.allowed, guard_result.reasons

    query_result = executor.execute(sql)
    assert query_result.row_count >= 1
    assert float(query_result.rows[0]["total_expense"]) == pytest.approx(10600.0)


def test_rejected_sql_never_reaches_executor(
    guard: SqlGuard, executor: DuckDBExecutor
) -> None:
    dangerous_sql = "DROP TABLE dwd.dwd_patient"
    guard_result = guard.validate(dangerous_sql)
    assert not guard_result.allowed
    # Simulate the agent's guard gate: only execute if allowed
    executed = False
    if guard_result.allowed:
        executor.execute(dangerous_sql)
        executed = True
    assert not executed
