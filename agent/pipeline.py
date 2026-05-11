import time
from agent import sql_gen, sql_guard, executor, retriever, intent, prompt_builder
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


# ── 异步主流程 ────────────────────────────────────────────────────────────────

async def run(question: str, session_id: str = "", user_id: str = "") -> dict:
    start = time.time()

    # 1. 获取对话历史
    history = session_store.get_history(session_id) if session_id else []

    # 2. 意图识别
    intent_result = await intent.classify_async(question, history)
    intent_type = intent_result["intent"]

    # 3. 根据意图分支处理
    if intent_type == "OUT_OF_SCOPE":
        answer = "该问题超出数据查询范围，请提出与医疗数据相关的问题。"
        _save_and_log(session_id, user_id, question, "", "out_of_scope", 0, start, answer, intent_type)
        return _make_response(answer, "", [], 0, "out_of_scope", session_id)

    if intent_type == "ASK_CONCEPT":
        answer = await sql_gen.explain_concept_async(question)
        _save_and_log(session_id, user_id, question, "", "concept", 0, start, answer, intent_type)
        return _make_response(answer, "", [], 0, "concept", session_id)

    # QUERY_DATA / FOLLOWUP → 走 SQL 生成流程

    # 4. 检索相关 schema（Milvus 优先，兜底全量）
    retrieved_tables = []
    try:
        docs = await retriever.retrieve_async(question, top_k=3)
        schema_context = "\n\n".join(d.full_text for d in docs)
        retrieved_tables = [d.table_name for d in docs]
    except Exception:
        schema_context = FALLBACK_SCHEMA

    # 5. 构建 prompt 并生成 SQL
    system_msg, messages = prompt_builder.build_sql_prompt(question, schema_context, history)
    sql = await sql_gen.generate_sql_with_prompt_async(system_msg, messages)
    if sql == "CANNOT_GENERATE":
        answer = "无法将该问题转化为数据查询，请换种方式提问。"
        _save_and_log(session_id, user_id, question, "", "cannot_generate", 0, start, answer, intent_type, retrieved_tables)
        return _make_response(answer, "", [], 0, "cannot_generate", session_id)

    # 6. 安全校验 + 自动注入 LIMIT
    guard = sql_guard.validate(sql)
    if not guard["valid"]:
        answer = f"SQL 安全校验未通过：{guard['reason']}"
        _save_and_log(session_id, user_id, question, sql, "guard_rejected", 0, start, answer, intent_type, retrieved_tables, "rejected")
        return _make_response(answer, sql, [], 0, "guard_rejected", session_id)
    sql = sql_guard.add_limit(sql)

    # 7. 执行查询（失败时自动修复重试，最多 2 次）
    result = await executor.execute_async(sql)
    if result["error"]:
        for attempt in range(2):
            fixed_sql = await sql_gen.repair_sql_async(question, sql, result["error"], schema_context)
            if fixed_sql == "CANNOT_REPAIR":
                break
            guard = sql_guard.validate(fixed_sql)
            if not guard["valid"]:
                break
            sql = sql_guard.add_limit(fixed_sql)
            result = await executor.execute_async(sql)
            if not result["error"]:
                break
        if result["error"]:
            answer = f"查询执行失败：{result['error']}"
            _save_and_log(session_id, user_id, question, sql, "sql_error", 0, start, answer, intent_type, retrieved_tables, "passed")
            return _make_response(answer, sql, [], 0, "sql_error", session_id)

    # 8. 解释结果
    answer = await sql_gen.explain_result_async(question, sql, result["data"])
    _save_and_log(session_id, user_id, question, sql, "success", result["row_count"], start, answer, intent_type, retrieved_tables, "passed")

    return _make_response(answer, sql, result["data"], result["row_count"], "success", session_id)


def _make_response(answer, sql, data, row_count, status, session_id):
    return {
        "answer": answer,
        "sql": sql,
        "data": data,
        "row_count": row_count,
        "status": status,
        "session_id": session_id,
    }


def _save_and_log(session_id, user_id, question, sql, status, row_count, start, answer,
                   intent="", retrieved_tables=None, guard_result=""):
    latency = int((time.time() - start) * 1000)
    logger.log(session_id, user_id, question, sql, status, row_count, latency,
               intent=intent, retrieved_tables=retrieved_tables or [],
               guard_result=guard_result, answer=answer)
    session_store.add_message(session_id, "user", question)
    session_store.add_message(session_id, "assistant", answer)
