"""Initialize a local DuckDB warehouse from bundled medical mock CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=None,
        help="DuckDB database path. Defaults to ai-data-agent/data/medical_dw.db.",
    )
    parser.add_argument(
        "--csv-root",
        default=None,
        help="Medical mock CSV root. Defaults to mock/medical/csv at the repository root.",
    )
    args = parser.parse_args()

    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise SystemExit("duckdb is required. Install with `pip install duckdb`.") from exc

    ai_root = Path(__file__).resolve().parents[1]
    repo_root = ai_root.parent
    database = Path(args.database) if args.database else ai_root / "data" / "medical_dw.db"
    csv_root = Path(args.csv_root) if args.csv_root else repo_root / "mock" / "medical" / "csv"
    database.parent.mkdir(parents=True, exist_ok=True)

    required_files = [
        "patient_info_202501.csv",
        "inpatient_info_202501.csv",
        "inpatient_order_202501.csv",
        "diag_info_202501.csv",
        "lab_info_202501.csv",
    ]
    missing = [name for name in required_files if not (csv_root / name).exists()]
    if missing:
        raise SystemExit(f"Missing CSV files under {csv_root}: {', '.join(missing)}")

    con = duckdb.connect(str(database))
    try:
        _initialize(con, csv_root)
    finally:
        con.close()

    print(f"initialized_duckdb={database}")
    return 0


def _initialize(con, csv_root: Path) -> None:
    for schema in ["ods", "dwd", "dws", "ads", "dim", "dq", "mpi", "mdm"]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    con.execute(
        f"""
CREATE OR REPLACE TABLE ods.ods_patient_info AS
SELECT
  "patient_id(患者ID)" AS patient_id,
  "patient_name(患者姓名)" AS patient_name,
  "gender(性别)" AS gender,
  CAST("birth_date(出生日期)" AS DATE) AS birth_date,
  "id_card(身份证号)" AS id_card,
  "phone(联系电话)" AS phone,
  "address(地址)" AS address,
  CAST("create_time(创建时间)" AS TIMESTAMP) AS create_time
FROM read_csv_auto('{_sql_path(csv_root / "patient_info_202501.csv")}', header=true)
"""
    )
    con.execute(
        f"""
CREATE OR REPLACE TABLE ods.ods_inpatient_info AS
SELECT
  "inpatient_id(住院ID)" AS inpatient_id,
  "patient_id(患者ID)" AS patient_id,
  "visit_sn(就诊流水号)" AS visit_sn,
  CAST("admission_time(入院时间)" AS TIMESTAMP) AS admission_time,
  CAST("discharge_time(出院时间)" AS TIMESTAMP) AS discharge_time,
  "ward_code(病区编码)" AS ward_code,
  "dept_code(科室编码)" AS dept_code,
  "doctor_id(医生ID)" AS doctor_id,
  "status(状态)" AS status,
  CAST("create_time(创建时间)" AS TIMESTAMP) AS create_time
FROM read_csv_auto('{_sql_path(csv_root / "inpatient_info_202501.csv")}', header=true)
"""
    )
    con.execute(
        f"""
CREATE OR REPLACE TABLE ods.ods_inpatient_order AS
SELECT
  "order_id(医嘱ID)" AS order_id,
  "patient_id(患者ID)" AS patient_id,
  "visit_sn(就诊流水号)" AS visit_sn,
  "drug_code(药品编码)" AS drug_code,
  "drug_name(药品名称)" AS drug_name,
  CAST("dose(剂量)" AS DOUBLE) AS dose,
  "unit(单位)" AS unit,
  CAST("order_time(医嘱时间)" AS TIMESTAMP) AS order_time,
  "doctor_id(医生ID)" AS doctor_id,
  "order_status(医嘱状态)" AS order_status,
  CAST("create_time(创建时间)" AS TIMESTAMP) AS create_time
FROM read_csv_auto('{_sql_path(csv_root / "inpatient_order_202501.csv")}', header=true)
"""
    )
    con.execute(
        f"""
CREATE OR REPLACE TABLE ods.ods_diagnosis_record AS
SELECT
  "diag_id(诊断ID)" AS diag_id,
  "patient_id(患者ID)" AS patient_id,
  "visit_sn(就诊流水号)" AS visit_sn,
  "diag_code(诊断编码)" AS diag_code,
  "diag_name(诊断名称)" AS diag_name,
  "diag_type(诊断类型)" AS diag_type,
  "doctor_id(医生ID)" AS doctor_id,
  CAST("diag_time(诊断时间)" AS TIMESTAMP) AS diag_time,
  CAST("create_time(创建时间)" AS TIMESTAMP) AS create_time
FROM read_csv_auto('{_sql_path(csv_root / "diag_info_202501.csv")}', header=true)
"""
    )
    con.execute(
        f"""
CREATE OR REPLACE TABLE ods.ods_lab_result AS
SELECT
  "lab_id(检验ID)" AS lab_id,
  "patient_id(患者ID)" AS patient_id,
  "visit_sn(就诊流水号)" AS visit_sn,
  "lab_code(检验编码)" AS lab_code,
  "lab_name(检验名称)" AS lab_name,
  "result_value(结果值)" AS result_value,
  "normal_range(正常范围)" AS normal_range,
  "result_flag(结果标志)" AS result_flag,
  CAST("collect_time(采集时间)" AS TIMESTAMP) AS collect_time,
  CAST("report_time(报告时间)" AS TIMESTAMP) AS report_time,
  CAST("create_time(创建时间)" AS TIMESTAMP) AS create_time
FROM read_csv_auto('{_sql_path(csv_root / "lab_info_202501.csv")}', header=true)
"""
    )

    con.execute(
        """
CREATE OR REPLACE TABLE dim.dim_dept_dict AS
SELECT * FROM (
  VALUES
    ('ONCO01', '肿瘤内科'),
    ('ONCO02', '肿瘤放疗科'),
    ('SURG01', '肿瘤外科'),
    ('HEMA01', '血液科')
) AS t(dept_code, dept_name)
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dim.dim_drug_dict AS
SELECT * FROM (
  VALUES
    ('DRUG001', '注射用紫杉醇', 'ANTITUMOR', '化疗'),
    ('DRUG002', '奥沙利铂注射液', 'ANTITUMOR', '化疗'),
    ('DRUG003', '卡培他滨片', 'ANTITUMOR', '化疗'),
    ('DRUG004', '吉西他滨注射液', 'ANTITUMOR', '化疗')
) AS t(drug_code, drug_name, drug_category, drug_type)
"""
    )

    con.execute(
        """
CREATE OR REPLACE TABLE dwd.dwd_patient AS
SELECT patient_id, patient_name, gender, birth_date, create_time AS etl_time
FROM ods.ods_patient_info
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dwd.dwd_visit AS
SELECT
  visit_sn,
  patient_id,
  '1' AS visit_type,
  dept_code,
  admission_time AS visit_start_time,
  discharge_time AS visit_end_time,
  create_time AS etl_time
FROM ods.ods_inpatient_info
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dws.dws_tumor_drug_usage_1d AS
SELECT
  CAST(order_time AS DATE) AS stat_date,
  o.drug_code,
  COALESCE(d.drug_name, o.drug_name) AS drug_name,
  COALESCE(d.drug_category, 'ANTITUMOR') AS drug_category,
  d.drug_type AS chemo_regimen,
  i.dept_code,
  COALESCE(dept.dept_name, i.dept_code) AS dept_name,
  '1' AS visit_type,
  COUNT(DISTINCT o.patient_id) AS patient_cnt,
  COUNT(*) AS order_cnt,
  SUM(o.dose) AS total_dose_mg,
  COUNT(DISTINCT d.drug_type) AS regimen_cnt,
  ROUND(SUM(o.dose * 8.8), 2) AS drug_expense_total,
  ROUND(SUM(o.dose * 8.8), 2) AS drug_amount,
  8.8 AS avg_unit_price,
  SUM(CASE WHEN o.dose > 1000 THEN 1 ELSE 0 END) AS exceed_dose_cnt,
  0 AS adr_suspect_cnt,
  CURRENT_TIMESTAMP AS etl_time
FROM ods.ods_inpatient_order o
LEFT JOIN ods.ods_inpatient_info i ON o.visit_sn = i.visit_sn
LEFT JOIN dim.dim_dept_dict dept ON i.dept_code = dept.dept_code
LEFT JOIN dim.dim_drug_dict d ON o.drug_code = d.drug_code
GROUP BY 1, 2, 3, 4, 5, 6, 7
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE ads.ads_drug_usage_trend AS
SELECT
  stat_date,
  strftime(stat_date, '%Y-%m') AS stat_month,
  drug_code,
  drug_name,
  drug_category,
  chemo_regimen,
  CAST(SUM(patient_cnt) AS INTEGER) AS patient_cnt,
  CAST(0 AS DECIMAL(5,2)) AS patient_cnt_mom,
  CAST(0 AS DECIMAL(5,2)) AS patient_cnt_yoy,
  CAST(SUM(order_cnt) AS INTEGER) AS order_cnt,
  SUM(total_dose_mg) AS total_dose_mg,
  SUM(drug_expense_total) AS drug_expense_total,
  SUM(drug_amount) AS drug_amount,
  CAST(0 AS DECIMAL(5,2)) AS expense_mom,
  ROUND(SUM(total_dose_mg) / NULLIF(SUM(patient_cnt), 0), 4) AS avg_dose_per_patient_mg,
  ROUND(SUM(drug_expense_total) / NULLIF(SUM(patient_cnt), 0), 2) AS avg_expense_per_patient,
  arg_max(dept_name, patient_cnt) AS top1_dept_name,
  CAST(MAX(patient_cnt) AS INTEGER) AS top1_dept_patient_cnt,
  NULL AS top2_dept_name,
  NULL AS top3_dept_name,
  ROW_NUMBER() OVER (PARTITION BY stat_date ORDER BY SUM(patient_cnt) DESC) AS usage_rank,
  CURRENT_TIMESTAMP AS etl_time
FROM dws.dws_tumor_drug_usage_1d
GROUP BY stat_date, drug_code, drug_name, drug_category, chemo_regimen
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dws.dws_lab_abnormal_1d AS
SELECT
  CAST(l.report_time AS DATE) AS stat_date,
  l.lab_code AS test_item_code,
  COALESCE(NULLIF(l.lab_name, ''), '未维护检验项目') AS test_item_name,
  CASE
    WHEN l.lab_name LIKE '%肿瘤标志物%' THEN '肿瘤标志物'
    WHEN l.lab_name LIKE '%血%' THEN '血液'
    ELSE '生化'
  END AS test_category,
  '' AS unit,
  i.dept_code,
  dept.dept_name,
  COUNT(*) AS test_total_cnt,
  COUNT(DISTINCT l.patient_id) AS patient_cnt,
  SUM(CASE WHEN l.result_flag = '1' THEN 1 ELSE 0 END) AS high_value_cnt,
  SUM(CASE WHEN l.result_flag = '2' THEN 1 ELSE 0 END) AS low_value_cnt,
  SUM(CASE WHEN l.result_flag IN ('1', '2') AND TRY_CAST(l.result_value AS DOUBLE) >= 100 THEN 1 ELSE 0 END) AS critical_value_cnt,
  SUM(CASE WHEN l.result_flag IN ('1', '2') AND TRY_CAST(l.result_value AS DOUBLE) >= 100 THEN 1 ELSE 0 END) AS critical_handled_cnt,
  25.0 AS critical_avg_handle_min,
  SUM(COALESCE(TRY_CAST(l.result_value AS DOUBLE), 0)) AS result_sum,
  MAX(COALESCE(TRY_CAST(l.result_value AS DOUBLE), 0)) AS result_max,
  MIN(COALESCE(TRY_CAST(l.result_value AS DOUBLE), 0)) AS result_min,
  CURRENT_TIMESTAMP AS etl_time
FROM ods.ods_lab_result l
LEFT JOIN ods.ods_inpatient_info i ON l.visit_sn = i.visit_sn
LEFT JOIN dim.dim_dept_dict dept ON i.dept_code = dept.dept_code
GROUP BY 1, 2, 3, 4, 5, 6, 7
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE ads.ads_inpatient_quality_board AS
WITH stay AS (
  SELECT
    CAST(discharge_time AS DATE) AS stat_date,
    i.dept_code,
    COALESCE(dept.dept_name, i.dept_code) AS dept_name,
    COUNT(*) AS inpatient_discharge_cnt,
    AVG(ABS(date_diff('day', admission_time, discharge_time))) AS avg_inpatient_days,
    SUM(CASE WHEN ABS(date_diff('day', admission_time, discharge_time)) > 30 THEN 1 ELSE 0 END) AS long_stay_cnt
  FROM ods.ods_inpatient_info i
  LEFT JOIN dim.dim_dept_dict dept ON i.dept_code = dept.dept_code
  WHERE discharge_time IS NOT NULL
  GROUP BY 1, 2, 3
),
critical AS (
  SELECT
    stat_date,
    dept_code,
    SUM(critical_value_cnt) AS critical_value_total_cnt,
    SUM(critical_handled_cnt) AS critical_handled_in_30min_cnt,
    AVG(critical_avg_handle_min) AS critical_avg_handle_min
  FROM dws.dws_lab_abnormal_1d
  GROUP BY 1, 2
)
SELECT
  s.stat_date,
  s.dept_code,
  s.dept_name,
  CASE WHEN s.dept_code LIKE 'ONCO%' THEN '肿瘤专科' ELSE '综合科室' END AS dept_type,
  CAST(s.inpatient_discharge_cnt AS INTEGER) AS inpatient_discharge_cnt,
  ROUND(s.avg_inpatient_days, 2) AS avg_inpatient_days,
  ROUND(s.avg_inpatient_days, 2) AS avg_inpatient_days_7d_avg,
  CAST(s.long_stay_cnt AS INTEGER) AS long_stay_cnt,
  ROUND(100.0 * s.long_stay_cnt / NULLIF(s.inpatient_discharge_cnt, 0), 2) AS long_stay_rate,
  s.inpatient_discharge_cnt AS discharge_cnt_for_readm,
  0 AS readmission_30d_cnt,
  0.0 AS readmission_30d_rate,
  0 AS readmission_15d_cnt,
  0 AS surgery_cnt,
  0 AS complication_cnt,
  0.0 AS complication_rate,
  0 AS mortality_cnt,
  0.0 AS mortality_rate,
  COALESCE(c.critical_value_total_cnt, 0) AS critical_value_total_cnt,
  COALESCE(c.critical_handled_in_30min_cnt, 0) AS critical_handled_in_30min_cnt,
  CASE WHEN COALESCE(c.critical_value_total_cnt, 0) = 0 THEN 100.0
       ELSE ROUND(100.0 * c.critical_handled_in_30min_cnt / c.critical_value_total_cnt, 2)
  END AS critical_timely_rate,
  COALESCE(c.critical_avg_handle_min, 0) AS critical_avg_handle_min,
  s.inpatient_discharge_cnt AS tumor_patient_cnt,
  s.inpatient_discharge_cnt AS tumor_chemo_patient_cnt,
  ROUND(s.avg_inpatient_days, 2) AS tumor_avg_inpatient_days,
  CURRENT_TIMESTAMP AS etl_time
FROM stay s
LEFT JOIN critical c ON s.stat_date = c.stat_date AND s.dept_code = c.dept_code
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dq.dq_check_result AS
SELECT
  'DQ-001' AS rule_code,
  'patient_id_not_null' AS rule_name,
  'passed' AS check_status,
  0 AS issue_count,
  CURRENT_TIMESTAMP AS check_time
UNION ALL
SELECT
  'DQ-DRUG-DEPT-NULL' AS rule_code,
  '抗肿瘤药物汇总科室编码非空检查' AS rule_name,
  CASE WHEN COUNT(*) = 0 THEN 'passed' ELSE 'failed' END AS check_status,
  CAST(COUNT(*) AS INTEGER) AS issue_count,
  CURRENT_TIMESTAMP AS check_time
FROM dws.dws_tumor_drug_usage_1d
WHERE dept_code IS NULL OR dept_code = ''
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE dq.dq_issue_detail AS
SELECT
  'DQ-DRUG-DEPT-NULL' AS rule_code,
  stat_date,
  drug_code,
  drug_name,
  dept_code,
  dept_name,
  drug_amount,
  'visit_sn 未能关联住院记录，导致科室缺失' AS issue_reason,
  CURRENT_TIMESTAMP AS check_time
FROM dws.dws_tumor_drug_usage_1d
WHERE dept_code IS NULL OR dept_code = ''
"""
    )
    con.execute(
        """
CREATE OR REPLACE TABLE ads.ads_dq_result_summary AS
SELECT
  CAST(CURRENT_DATE AS DATE) AS stat_date,
  'DWS' AS data_layer,
  'dws.dws_tumor_drug_usage_1d' AS table_name,
  COUNT(*) AS rule_total_cnt,
  SUM(CASE WHEN check_status = 'passed' THEN 1 ELSE 0 END) AS rule_pass_cnt,
  SUM(CASE WHEN check_status = 'failed' THEN 1 ELSE 0 END) AS rule_fail_cnt,
  ROUND(100.0 * SUM(CASE WHEN check_status = 'passed' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS rule_pass_rate,
  0 AS record_total_cnt,
  0 AS record_pass_cnt,
  SUM(issue_count) AS record_fail_cnt,
  100.0 AS record_pass_rate,
  0 AS critical_fail_cnt,
  SUM(CASE WHEN rule_code = 'DQ-DRUG-DEPT-NULL' THEN issue_count ELSE 0 END) AS high_fail_cnt,
  0 AS medium_fail_cnt,
  0 AS low_fail_cnt,
  100.0 - LEAST(SUM(issue_count) * 5.0, 100.0) AS dq_score,
  0.0 AS dq_score_delta,
  'HIGH' AS severity,
  SUM(issue_count) AS issue_count,
  '[' || string_agg('{"rule_code":"' || rule_code || '","rule_name":"' || rule_name || '","issue_count":' || issue_count || '}', ',') || ']' AS fail_rule_detail_json,
  CURRENT_TIMESTAMP AS etl_time
FROM dq.dq_check_result
"""
    )


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


if __name__ == "__main__":
    raise SystemExit(main())
