# SQL 安全校验 - 待实现（Phase 1）
import sqlglot

WHITELIST = {
    "ads_dq_result_summary", "ads_patient_mpi_summary",
    "ads_drug_usage_trend", "ads_tumor_report_monthly",
    "ads_expense_by_tumor_type", "ads_inpatient_quality_board",
    "dq_check_result", "dq_issue_detail", "mpi_cross_reference",
}

FORBIDDEN = {"insert", "update", "delete", "drop", "truncate", "alter", "create"}

def validate(sql: str) -> dict:
    # 待完整实现（Phase 1）
    lower = sql.lower()
    for word in FORBIDDEN:
        if word in lower:
            return {"valid": False, "reason": f"禁止执行 {word.upper()} 操作"}
    return {"valid": True, "reason": ""}
