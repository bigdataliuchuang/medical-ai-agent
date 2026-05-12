"""Tests for the enhanced SQL guard (sensitive fields, time range, blocklist)."""

from __future__ import annotations

import pytest

from ai_data_agent.text2sql.sql_guard import SqlGuard, SqlGuardConfig, SqlGuardResult


@pytest.fixture()
def guard() -> SqlGuard:
    return SqlGuard(
        allowed_schemas=["ads", "dws", "dwd", "dim", "dq"],
        deny_select_star=True,
        require_limit_for_detail_query=True,
        require_time_filter=False,
        block_sensitive_fields=True,
    )


@pytest.fixture()
def guard_time() -> SqlGuard:
    return SqlGuard(
        allowed_schemas=["ads", "dws", "dwd", "dim", "dq"],
        require_time_filter=True,
    )


# ------------------------------------------------------------------
# Blocklist (high-risk DML/DDL keywords)
# ------------------------------------------------------------------


def test_drop_table_blocked(guard: SqlGuard) -> None:
    result = guard.validate("DROP TABLE ads.ads_drug_usage_trend")
    assert not result.allowed
    assert result.risk_level == "HIGH"
    assert any("DROP" in r for r in result.reasons)


def test_delete_blocked(guard: SqlGuard) -> None:
    result = guard.validate("DELETE FROM dwd.dwd_visit WHERE visit_id = '1'")
    assert not result.allowed
    assert result.risk_level == "HIGH"


def test_update_blocked(guard: SqlGuard) -> None:
    result = guard.validate("UPDATE dwd.dwd_visit SET visit_type='门诊' WHERE visit_id='1'")
    assert not result.allowed


def test_insert_blocked(guard: SqlGuard) -> None:
    result = guard.validate("INSERT INTO dwd.dwd_visit VALUES (1,'test')")
    assert not result.allowed


def test_truncate_blocked(guard: SqlGuard) -> None:
    result = guard.validate("TRUNCATE TABLE dwd.dwd_visit")
    assert not result.allowed


def test_create_blocked(guard: SqlGuard) -> None:
    result = guard.validate("CREATE TABLE test (id INT)")
    assert not result.allowed


# ------------------------------------------------------------------
# Sensitive field detection
# ------------------------------------------------------------------


def test_id_card_field_blocked(guard: SqlGuard) -> None:
    sql = "SELECT id_card, mpi_id FROM dwd.dwd_patient WHERE stat_date = '2025-01' LIMIT 10"
    result = guard.validate(sql)
    assert not result.allowed
    assert "id_card" in result.sensitive_fields
    assert result.risk_level == "HIGH"


def test_phone_field_blocked(guard: SqlGuard) -> None:
    sql = "SELECT phone, dept_code FROM dwd.dwd_patient WHERE stat_date = '2025-01' LIMIT 10"
    result = guard.validate(sql)
    assert not result.allowed
    assert "phone" in result.sensitive_fields


def test_patient_name_blocked(guard: SqlGuard) -> None:
    sql = "SELECT patient_name, mpi_id FROM dwd.dwd_patient WHERE stat_date = '2025-01' LIMIT 10"
    result = guard.validate(sql)
    assert not result.allowed
    assert "patient_name" in result.sensitive_fields


def test_non_sensitive_fields_allowed(guard: SqlGuard) -> None:
    sql = (
        "SELECT dept_code, COUNT(DISTINCT mpi_id) AS cnt "
        "FROM dwd.dwd_visit "
        "WHERE stat_date = '2025-01' "
        "GROUP BY dept_code "
        "LIMIT 20"
    )
    result = guard.validate(sql)
    assert result.allowed
    assert result.sensitive_fields == []
    assert result.risk_level == "LOW"


# ------------------------------------------------------------------
# Time range requirement
# ------------------------------------------------------------------


def test_time_filter_required_and_present(guard_time: SqlGuard) -> None:
    sql = (
        "SELECT COUNT(DISTINCT mpi_id) AS cnt "
        "FROM dwd.dwd_visit "
        "WHERE visit_date >= '2025-01-01' "
        "LIMIT 1"
    )
    result = guard_time.validate(sql)
    assert result.allowed


def test_time_filter_required_and_missing(guard_time: SqlGuard) -> None:
    sql = (
        "SELECT COUNT(DISTINCT mpi_id) AS cnt "
        "FROM dwd.dwd_visit "
        "WHERE dept_code = 'D001' "
        "LIMIT 1"
    )
    result = guard_time.validate(sql)
    assert not result.allowed
    assert any("time range" in r for r in result.reasons)


def test_stat_month_counts_as_time_filter(guard_time: SqlGuard) -> None:
    sql = (
        "SELECT stat_month, SUM(drug_expense_total) "
        "FROM ads.ads_drug_usage_trend "
        "WHERE stat_month >= '2025-01' "
        "LIMIT 12"
    )
    result = guard_time.validate(sql)
    assert result.allowed


# ------------------------------------------------------------------
# Existing rules still work
# ------------------------------------------------------------------


def test_select_star_still_blocked(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT * FROM ads.ads_drug_usage_trend WHERE stat_month='2025-01' LIMIT 10"
    )
    assert not result.allowed
    assert any("SELECT *" in r for r in result.reasons)


def test_missing_limit_still_blocked(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT dept_code, COUNT(*) AS cnt FROM dwd.dwd_visit WHERE stat_date='2025-01' GROUP BY dept_code"
    )
    assert not result.allowed
    assert any("LIMIT" in r for r in result.reasons)


def test_unqualified_table_blocked(guard: SqlGuard) -> None:
    result = guard.validate("SELECT dept_code FROM dwd_visit WHERE stat_date='2025-01' LIMIT 10")
    assert not result.allowed


def test_risk_level_medium_for_limit_issue(guard: SqlGuard) -> None:
    result = guard.validate(
        "SELECT dept_code FROM dwd.dwd_visit WHERE stat_date='2025-01' GROUP BY dept_code"
    )
    assert not result.allowed
    assert result.risk_level == "MEDIUM"


# ------------------------------------------------------------------
# SqlGuardConfig factory
# ------------------------------------------------------------------


def test_from_config_creates_guard() -> None:
    config = SqlGuardConfig(
        allowed_schemas=frozenset(["ads"]),
        deny_select_star=True,
        require_limit=True,
        block_sensitive_fields=False,
    )
    guard = SqlGuard.from_config(config)
    result = guard.validate(
        "SELECT id_card FROM ads.ads_drug_usage_trend WHERE stat_month='2025-01' LIMIT 10"
    )
    # sensitive field detection disabled → should pass (other rules may still fail)
    assert result.sensitive_fields == []
