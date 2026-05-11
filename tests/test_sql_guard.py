"""Tests for production SQL safety validation."""

from __future__ import annotations

from ai_data_agent.text2sql.sql_guard import SqlGuard


def test_sql_guard_allows_count_star():
    guard = SqlGuard(allowed_schemas=["dws"])

    result = guard.validate(
        "SELECT COUNT(*) AS total_records "
        "FROM dws.dws_tumor_drug_usage_1d "
        "LIMIT 100"
    )

    assert result.allowed is True
    assert "SELECT * is not allowed." not in result.reasons


def test_sql_guard_rejects_projected_star():
    guard = SqlGuard(allowed_schemas=["dws"])

    result = guard.validate("SELECT * FROM dws.dws_tumor_drug_usage_1d LIMIT 100")

    assert result.allowed is False
    assert "SELECT * is not allowed." in result.reasons


def test_sql_guard_rejects_table_qualified_projected_star():
    guard = SqlGuard(allowed_schemas=["dws"])

    result = guard.validate("SELECT dws.dws_tumor_drug_usage_1d.* FROM dws.dws_tumor_drug_usage_1d LIMIT 100")

    assert result.allowed is False
    assert "SELECT * is not allowed." in result.reasons
