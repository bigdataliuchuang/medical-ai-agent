import os
import sqlglot
from sqlglot import exp

WHITELIST = set(
    os.getenv(
        "SQL_WHITELIST_TABLES",
        "ads_dq_result_summary,ads_patient_mpi_summary,ads_drug_usage_trend,"
        "ads_tumor_report_monthly,ads_expense_by_tumor_type,ads_inpatient_quality_board,"
        "dq_check_result,dq_issue_detail,mpi_cross_reference",
    ).split(",")
)

FORBIDDEN_TYPES = {exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable}
FORBIDDEN_KEYWORDS = {"insert", "update", "delete", "drop", "truncate", "alter", "create"}


def validate(sql: str) -> dict:
    sql_stripped = sql.strip().rstrip(";")

    # 拒绝多语句
    if ";" in sql_stripped:
        return {"valid": False, "reason": "禁止执行多条 SQL 语句"}

    lower = sql_stripped.lower()
    for word in FORBIDDEN_KEYWORDS:
        if lower.startswith(word) or f" {word} " in lower:
            return {"valid": False, "reason": f"禁止执行 {word.upper()} 操作"}

    # SQLGlot 解析 + 表名白名单校验
    try:
        ast = sqlglot.parse_one(sql_stripped, read="mysql")
    except Exception:
        return {"valid": False, "reason": "SQL 语法解析失败"}

    # 检查是否包含写操作节点
    for node in ast.walk():
        if isinstance(node, tuple(FORBIDDEN_TYPES)):
            return {"valid": False, "reason": f"禁止执行写操作"}

    # 提取表名并检查白名单
    tables = set()
    for table in ast.find_all(exp.Table):
        name = table.name
        tables.add(name)

    unknown = tables - WHITELIST
    if unknown:
        return {"valid": False, "reason": f"表 {', '.join(unknown)} 不在白名单中"}

    return {"valid": True, "reason": ""}
