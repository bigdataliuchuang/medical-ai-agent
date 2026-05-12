"""Shared DuckDB fixtures for integration tests.

Sets up an in-memory DuckDB database that mirrors the medical data warehouse
schema (dwd / dws / ads / dim) with a small set of deterministic test rows.
Tests can run entirely offline — no Doris, no Milvus, no API keys needed.
"""

from __future__ import annotations

import pytest
import duckdb


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;
CREATE SCHEMA IF NOT EXISTS ads;
CREATE SCHEMA IF NOT EXISTS dim;

-- ── dim tables ────────────────────────────────────────────────────────────
CREATE TABLE dim.dim_drug_dict (
    drug_code     VARCHAR PRIMARY KEY,
    drug_name     VARCHAR,
    drug_category VARCHAR,
    atc_code      VARCHAR,
    is_antitumor  BOOLEAN
);

CREATE TABLE dim.dim_dept_dict (
    dept_code VARCHAR PRIMARY KEY,
    dept_name VARCHAR,
    dept_type VARCHAR
);

CREATE TABLE dim.dim_diagnosis_dict (
    icd_code   VARCHAR PRIMARY KEY,
    icd_name   VARCHAR,
    tumor_type VARCHAR,
    category   VARCHAR
);

-- ── dwd tables ────────────────────────────────────────────────────────────
CREATE TABLE dwd.dwd_patient (
    mpi_id        VARCHAR PRIMARY KEY,
    gender        CHAR(1),
    birth_date    DATE,
    source_system VARCHAR,
    etl_date      DATE
);

CREATE TABLE dwd.dwd_visit (
    visit_id      VARCHAR PRIMARY KEY,
    mpi_id        VARCHAR,
    visit_type    VARCHAR,
    dept_code     VARCHAR,
    admit_date    TIMESTAMP,
    discharge_date TIMESTAMP,
    visit_date    DATE,
    hospital_code VARCHAR
);

CREATE TABLE dwd.dwd_diagnosis (
    diag_id        VARCHAR PRIMARY KEY,
    visit_id       VARCHAR,
    mpi_id         VARCHAR,
    diagnosis_code VARCHAR,
    diagnosis_name VARCHAR,
    diagnosis_type VARCHAR,
    visit_date     DATE
);

CREATE TABLE dwd.dwd_order (
    order_id     VARCHAR PRIMARY KEY,
    visit_id     VARCHAR,
    mpi_id       VARCHAR,
    drug_code    VARCHAR,
    drug_expense DECIMAL(12,2),
    order_status VARCHAR,
    order_date   DATE,
    dept_code    VARCHAR
);

CREATE TABLE dwd.dwd_expense_detail (
    expense_id       VARCHAR PRIMARY KEY,
    visit_id         VARCHAR,
    mpi_id           VARCHAR,
    expense_category VARCHAR,
    expense_amount   DECIMAL(12,2),
    dept_code        VARCHAR,
    expense_date     DATE
);

-- ── dws / ads tables ─────────────────────────────────────────────────────
CREATE TABLE dws.dws_tumor_drug_usage_1d (
    stat_date              DATE,
    dept_code              VARCHAR,
    drug_code              VARCHAR,
    drug_expense_total     DECIMAL(14,2),
    order_count            INTEGER,
    patient_count          INTEGER
);

CREATE TABLE ads.ads_dq_result_summary (
    stat_date   DATE,
    table_name  VARCHAR,
    rule_code   VARCHAR,
    issue_count INTEGER,
    pass_rate   DECIMAL(5,4)
);
"""

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_SEED = """
INSERT INTO dim.dim_drug_dict VALUES
    ('D001', '注射用紫杉醇', 'CHEMOTHERAPY', 'L01CD01', true),
    ('D002', '盐酸吉西他滨', 'CHEMOTHERAPY', 'L01BC05', true),
    ('D003', '奥沙利铂',     'CHEMOTHERAPY', 'L01XA03', true),
    ('D004', '盐酸多柔比星', 'CHEMOTHERAPY', 'L01DB01', true),
    ('D005', '阿莫西林',     'ANTIBIOTICS',  'J01CA04', false);

INSERT INTO dim.dim_dept_dict VALUES
    ('D101', '肿瘤内科', 'ONCOLOGY'),
    ('D102', '胸外科',   'SURGERY'),
    ('D103', '普通内科', 'INTERNAL');

INSERT INTO dim.dim_diagnosis_dict VALUES
    ('C34',   '支气管和肺的恶性肿瘤', 'lung',      'MALIGNANT'),
    ('C34.1', '上叶支气管或肺恶性肿瘤', 'lung',    'MALIGNANT'),
    ('C50',   '乳房恶性肿瘤',         'breast',    'MALIGNANT'),
    ('C18',   '结肠恶性肿瘤',         'colorectal','MALIGNANT');

INSERT INTO dwd.dwd_patient VALUES
    ('P001', 'M', '1960-03-15', 'HIS', '2025-01-01'),
    ('P002', 'F', '1972-07-22', 'EMR', '2025-01-01'),
    ('P003', 'M', '1955-11-08', 'HIS', '2025-01-01'),
    ('P004', 'F', '1948-05-30', 'CIS', '2025-01-01'),
    ('P005', 'M', '1980-09-14', 'HIS', '2025-01-01');

INSERT INTO dwd.dwd_visit VALUES
    ('V001', 'P001', '住院', 'D101', '2025-01-05 09:00', '2025-01-20 11:00', '2025-01-05', 'H001'),
    ('V002', 'P002', '住院', 'D101', '2025-01-10 08:30', '2025-01-25 14:00', '2025-01-10', 'H001'),
    ('V003', 'P003', '门诊', 'D102', NULL,               NULL,               '2025-01-12', 'H001'),
    ('V004', 'P004', '住院', 'D101', '2025-01-15 10:00', '2025-01-28 09:00', '2025-01-15', 'H001'),
    ('V005', 'P005', '门诊', 'D103', NULL,               NULL,               '2025-01-18', 'H001');

INSERT INTO dwd.dwd_diagnosis VALUES
    ('DG001', 'V001', 'P001', 'C34.1', '上叶肺癌', '主诊断', '2025-01-05'),
    ('DG002', 'V002', 'P002', 'C50',   '乳腺癌',   '主诊断', '2025-01-10'),
    ('DG003', 'V003', 'P003', 'C34',   '肺癌',     '主诊断', '2025-01-12'),
    ('DG004', 'V004', 'P004', 'C18',   '结肠癌',   '主诊断', '2025-01-15'),
    ('DG005', 'V001', 'P001', 'C34.1', '上叶肺癌', '出院诊断', '2025-01-05');

INSERT INTO dwd.dwd_order VALUES
    ('O001', 'V001', 'P001', 'D001', 3200.00, 'COMPLETED', '2025-01-06', 'D101'),
    ('O002', 'V001', 'P001', 'D002', 1800.00, 'COMPLETED', '2025-01-08', 'D101'),
    ('O003', 'V002', 'P002', 'D003', 2400.00, 'COMPLETED', '2025-01-12', 'D101'),
    ('O004', 'V004', 'P004', 'D001', 3200.00, 'COMPLETED', '2025-01-16', 'D101'),
    ('O005', 'V004', 'P004', 'D004', 1500.00, 'CANCELLED', '2025-01-17', 'D101'),
    ('O006', 'V003', 'P003', 'D005',  120.00, 'COMPLETED', '2025-01-12', 'D102');

INSERT INTO dwd.dwd_expense_detail VALUES
    ('E001', 'V001', 'P001', 'DRUG',  3200.00, 'D101', '2025-01-06'),
    ('E002', 'V001', 'P001', 'DRUG',  1800.00, 'D101', '2025-01-08'),
    ('E003', 'V001', 'P001', 'EXAM',   450.00, 'D101', '2025-01-07'),
    ('E004', 'V002', 'P002', 'DRUG',  2400.00, 'D101', '2025-01-12'),
    ('E005', 'V004', 'P004', 'DRUG',  3200.00, 'D101', '2025-01-16'),
    ('E006', 'V005', 'P005', 'EXAM',   200.00, 'D103', '2025-01-18');

INSERT INTO dws.dws_tumor_drug_usage_1d VALUES
    ('2025-01-06', 'D101', 'D001', 3200.00, 1, 1),
    ('2025-01-08', 'D101', 'D002', 1800.00, 1, 1),
    ('2025-01-12', 'D101', 'D003', 2400.00, 1, 1),
    ('2025-01-16', 'D101', 'D001', 3200.00, 1, 1);

INSERT INTO ads.ads_dq_result_summary VALUES
    ('2025-01-01', 'dwd.dwd_diagnosis', 'DQ-010', 2, 0.9800),
    ('2025-01-01', 'dwd.dwd_visit',     'DQ-020', 0, 1.0000),
    ('2025-01-01', 'dwd.dwd_order',     'DQ-030', 1, 0.9983),
    ('2025-01-02', 'dwd.dwd_diagnosis', 'DQ-010', 0, 1.0000);
"""


@pytest.fixture(scope="module")
def medical_db() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB database pre-loaded with medical test data."""
    conn = duckdb.connect(":memory:")
    conn.executemany  # warm-up attribute access
    conn.execute(_DDL)
    conn.execute(_SEED)
    yield conn
    conn.close()
