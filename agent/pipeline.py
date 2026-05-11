import time
from agent import sql_gen, sql_guard, executor, retriever
from memory import session_store
from audit import logger

# 兜底 schema（Milvus 不可用时使用）
FALLBACK_SCHEMA = """
表：ads.ads_dq_result_summary — DQ评分汇总，字段：stat_date, data_layer, dq_score, critical_fail_cnt
表：ads.ads_patient_mpi_summary — MPI去重汇总，字段：stat_date, total_mpi_cnt, exact_match_rate
表：ads.ads_drug_usage_trend — 药物用量趋势，字段：stat_month, drug_category, patient_cnt, drug_expense_total
表：ads.ads_tumor_report_monthly — 肿瘤月报，字段：report_month, tumor_type, patient_cnt, adr_rate
表：ads.ads_expense_by_tumor_type — 费用分析，字段：tumor_type, avg_expense_per_patient, drug_expense
表：ads.ads_inpatient_quality_board — 住院质量，字段：dept_name, avg_inpatient_days, surgery_cnt
表：dq.dq_check_result — DQ规则结果，字段：rule_name, severity_level, check_status
表：dq.dq_issue_detail — DQ问题明细，字段：rule_code, severity_level, issue_desc
"""


def run(question: str, session_id: str = "", user_id: str = "") -> dict:
    start = time.time()

    # 获取对话历史
    history = session_store.get_history(session_id) if session_id else []

    # 1. 检索相关 schema（Milvus 优先，兜底全量）
    try:
        docs = retriever.retrieve(question, top_k=3)
        schema_context = "\n\n".join(d.full_text for d in docs)
    except Exception:
        schema_context = FALLBACK_SCHEMA

    # 2. 生成 SQL
    sql = sql_gen.generate_sql(question, schema_context)
    if sql == "CANNOT_GENERATE":
        answer = "无法将该问题转化为数据查询，请换种方式提问。"
        _log(session_id, user_id, question, "", "cannot_generate", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": "", "data": [], "row_count": 0, "status": "cannot_generate", "session_id": session_id}

    # 3. 安全校验
    guard = sql_guard.validate(sql)
    if not guard["valid"]:
        answer = f"SQL 安全校验未通过：{guard['reason']}"
        _log(session_id, user_id, question, sql, "guard_rejected", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": sql, "data": [], "row_count": 0, "status": "guard_rejected", "session_id": session_id}

    # 4. 执行查询
    result = executor.execute(sql)
    if result["error"]:
        answer = f"查询执行失败：{result['error']}"
        _log(session_id, user_id, question, sql, "sql_error", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": sql, "data": [], "row_count": 0, "status": "sql_error", "session_id": session_id}

    # 5. 解释结果
    answer = sql_gen.explain_result(question, sql, result["data"])
    latency = int((time.time() - start) * 1000)
    _log(session_id, user_id, question, sql, "success", result["row_count"], start)

    # 保存对话历史
    session_store.add_message(session_id, "user", question)
    session_store.add_message(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sql": sql,
        "data": result["data"],
        "row_count": result["row_count"],
        "status": "success",
        "session_id": session_id,
    }


def _log(session_id: str, user_id: str, question: str, sql: str, status: str, row_count: int, start: float):
    latency = int((time.time() - start) * 1000)
    logger.log(session_id, user_id, question, sql, status, row_count, latency)
