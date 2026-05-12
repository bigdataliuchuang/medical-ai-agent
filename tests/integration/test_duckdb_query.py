"""Integration tests: real DuckDB queries against the medical schema.

These tests use the ``medical_db`` fixture (in-memory DuckDB) and exercise
realistic SQL patterns that the agent generates for medical data analysis.
No LLM, no Milvus, no Doris required.
"""

from __future__ import annotations

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Basic schema smoke tests
# ---------------------------------------------------------------------------


def test_patient_table_has_expected_rows(medical_db: duckdb.DuckDBPyConnection) -> None:
    result = medical_db.execute("SELECT COUNT(*) AS cnt FROM dwd.dwd_patient").fetchone()
    assert result[0] == 5


def test_drug_dict_antitumor_flag(medical_db: duckdb.DuckDBPyConnection) -> None:
    result = medical_db.execute(
        "SELECT COUNT(*) AS cnt FROM dim.dim_drug_dict WHERE is_antitumor = true"
    ).fetchone()
    assert result[0] == 4  # D001-D004 are antitumor


def test_visit_types_present(medical_db: duckdb.DuckDBPyConnection) -> None:
    rows = medical_db.execute(
        "SELECT DISTINCT visit_type FROM dwd.dwd_visit ORDER BY visit_type"
    ).fetchall()
    visit_types = {r[0] for r in rows}
    assert "住院" in visit_types
    assert "门诊" in visit_types


# ---------------------------------------------------------------------------
# Lung cancer patient count (common query pattern)
# ---------------------------------------------------------------------------


def test_lung_cancer_patient_count(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT COUNT(DISTINCT d.mpi_id) AS patient_count
        FROM dwd.dwd_diagnosis AS d
        JOIN dim.dim_diagnosis_dict AS dd ON d.diagnosis_code = dd.icd_code
        WHERE dd.tumor_type = 'lung'
          AND d.visit_date >= '2025-01-01'
        LIMIT 1
    """
    result = medical_db.execute(sql).fetchone()
    # P001 (C34.1 twice), P003 (C34) — two distinct patients
    assert result[0] == 2


# ---------------------------------------------------------------------------
# Antitumor drug expense by department
# ---------------------------------------------------------------------------


def test_antitumor_drug_expense_by_dept(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT
            dep.dept_name,
            SUM(o.drug_expense) AS total_expense
        FROM dwd.dwd_order AS o
        JOIN dim.dim_drug_dict AS dd ON o.drug_code = dd.drug_code
        JOIN dim.dim_dept_dict AS dep ON o.dept_code = dep.dept_code
        WHERE dd.is_antitumor = true
          AND o.order_status = 'COMPLETED'
          AND o.order_date >= '2025-01-01'
        GROUP BY dep.dept_name
        ORDER BY total_expense DESC
        LIMIT 10
    """
    rows = medical_db.execute(sql).fetchall()
    assert len(rows) >= 1
    dept_names = [r[0] for r in rows]
    assert "肿瘤内科" in dept_names
    # Total for 肿瘤内科: O001(3200) + O002(1800) + O003(2400) + O004(3200) = 10600
    dept_row = next(r for r in rows if r[0] == "肿瘤内科")
    assert dept_row[1] == pytest.approx(10600.00)


# ---------------------------------------------------------------------------
# DQ summary — tables with highest issue counts
# ---------------------------------------------------------------------------


def test_dq_tables_with_most_issues(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT table_name, SUM(issue_count) AS total_issues
        FROM ads.ads_dq_result_summary
        WHERE stat_date >= '2025-01-01'
        GROUP BY table_name
        ORDER BY total_issues DESC
        LIMIT 5
    """
    rows = medical_db.execute(sql).fetchall()
    assert len(rows) >= 1
    top_table = rows[0][0]
    # dwd.dwd_diagnosis has 2 issues on 2025-01-01 and 0 on 2025-01-02 = total 2
    assert "dwd_diagnosis" in top_table


# ---------------------------------------------------------------------------
# Join path: dwd_visit → dwd_diagnosis → dim_diagnosis_dict
# ---------------------------------------------------------------------------


def test_inpatient_cancer_patients(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT
            v.visit_type,
            COUNT(DISTINCT v.mpi_id) AS patient_count
        FROM dwd.dwd_visit AS v
        JOIN dwd.dwd_diagnosis AS d ON v.visit_id = d.visit_id
        JOIN dim.dim_diagnosis_dict AS dd ON d.diagnosis_code = dd.icd_code
        WHERE dd.category = 'MALIGNANT'
          AND v.visit_date >= '2025-01-01'
        GROUP BY v.visit_type
        ORDER BY patient_count DESC
        LIMIT 10
    """
    rows = medical_db.execute(sql).fetchall()
    type_map = {r[0]: r[1] for r in rows}
    # V001(P001,住院), V002(P002,住院), V003(P003,门诊), V004(P004,住院)
    assert type_map.get("住院", 0) == 3
    assert type_map.get("门诊", 0) == 1


# ---------------------------------------------------------------------------
# Expense breakdown by category
# ---------------------------------------------------------------------------


def test_expense_by_category(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT expense_category, SUM(expense_amount) AS total
        FROM dwd.dwd_expense_detail
        WHERE expense_date >= '2025-01-01'
        GROUP BY expense_category
        ORDER BY total DESC
        LIMIT 10
    """
    rows = medical_db.execute(sql).fetchall()
    cat_map = {r[0]: float(r[1]) for r in rows}
    assert "DRUG" in cat_map
    assert "EXAM" in cat_map
    # DRUG: 3200+1800+2400+3200 = 10600
    assert cat_map["DRUG"] == pytest.approx(10600.0)


# ---------------------------------------------------------------------------
# Cancelled orders must not count toward drug expense
# ---------------------------------------------------------------------------


def test_cancelled_orders_excluded(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT SUM(drug_expense) AS total
        FROM dwd.dwd_order
        WHERE order_status = 'COMPLETED'
          AND order_date >= '2025-01-01'
        LIMIT 1
    """
    total_completed = medical_db.execute(sql).fetchone()[0]

    sql_all = """
        SELECT SUM(drug_expense) AS total
        FROM dwd.dwd_order
        WHERE order_date >= '2025-01-01'
        LIMIT 1
    """
    total_all = medical_db.execute(sql_all).fetchone()[0]

    # O005 (CANCELLED, 1500) should make total_all > total_completed
    assert float(total_all) > float(total_completed)
    assert float(total_completed) == pytest.approx(10720.0)  # 3200+1800+2400+3200+120


# ---------------------------------------------------------------------------
# DWS aggregation layer
# ---------------------------------------------------------------------------


def test_dws_tumor_drug_usage_aggregation(medical_db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT
            dept_code,
            SUM(drug_expense_total) AS total,
            SUM(patient_count) AS patients
        FROM dws.dws_tumor_drug_usage_1d
        WHERE stat_date >= '2025-01-01'
        GROUP BY dept_code
        ORDER BY total DESC
        LIMIT 5
    """
    rows = medical_db.execute(sql).fetchall()
    assert len(rows) == 1  # only D101 (肿瘤内科) in test data
    assert rows[0][0] == "D101"
    assert float(rows[0][1]) == pytest.approx(10600.0)
