import time
from agent import sql_gen, sql_guard, executor
from memory import session_store
from audit import logger

# Phase 1 硬编码 schema（Phase 2 替换为 Milvus 检索）
HARDCODED_SCHEMA = """
表：ads.ads_dq_result_summary
描述：数据质量评分汇总表，每日统计各层 DQ 评分和失败规则数
字段：stat_date(日期), data_layer(数据层), dq_score(DQ评分), critical_fail_cnt(CRITICAL失败数), high_fail_cnt(HIGH失败数)

表：ads.ads_patient_mpi_summary
描述：患者主数据汇总表，统计 MPI 去重效果
字段：stat_date(日期), total_mpi_cnt(MPI患者数), mpi_coverage_rate(覆盖率), exact_match_rate(精确匹配率), fuzzy_match_rate(模糊匹配率)

表：ads.ads_drug_usage_trend
描述：抗肿瘤药物用量趋势表，按月按药品类别统计
字段：stat_month(月份), drug_category(药品类别), drug_name(药品名), patient_cnt(使用患者数), drug_expense_total(药品费用)

表：ads.ads_tumor_report_monthly
描述：肿瘤月度上报表，按化疗方案统计
字段：report_month(月份), chemo_regimen(化疗方案), tumor_type(肿瘤类型), patient_cnt(患者数), drug_expense_total(药品费用), adr_rate(不良反应率)

表：ads.ads_expense_by_tumor_type
描述：按肿瘤类型的费用分析表
字段：stat_date(日期), tumor_type(肿瘤类型), patient_cnt(患者数), avg_expense_per_patient(人均费用), drug_expense(药品费), exam_expense(检查费), surgery_expense(手术费)

表：ads.ads_inpatient_quality_board
描述：住院质量指标看板，按科室统计
字段：stat_date(日期), dept_name(科室名), avg_inpatient_days(平均住院天数), surgery_cnt(手术量), complication_rate(并发症率), readmission_30d_rate(再入院率)

表：dq.dq_check_result
描述：DQ 规则检查结果明细
字段：check_time(检查时间), rule_name(规则名), target_table(目标表), severity_level(严重级别), check_status(状态)

表：dq.dq_issue_detail
描述：DQ 问题明细
字段：check_time(检查时间), rule_code(规则编码), target_table(目标表), severity_level(严重级别), issue_desc(问题描述)
"""


def run(question: str, session_id: str = "", user_id: str = "") -> dict:
    start = time.time()

    # 获取对话历史
    history = session_store.get_history(session_id) if session_id else []

    # 1. 生成 SQL
    sql = sql_gen.generate_sql(question, HARDCODED_SCHEMA)
    if sql == "CANNOT_GENERATE":
        answer = "无法将该问题转化为数据查询，请换种方式提问。"
        _log(session_id, user_id, question, "", "cannot_generate", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": "", "data": [], "row_count": 0, "status": "cannot_generate", "session_id": session_id}

    # 2. 安全校验
    guard = sql_guard.validate(sql)
    if not guard["valid"]:
        answer = f"SQL 安全校验未通过：{guard['reason']}"
        _log(session_id, user_id, question, sql, "guard_rejected", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": sql, "data": [], "row_count": 0, "status": "guard_rejected", "session_id": session_id}

    # 3. 执行查询
    result = executor.execute(sql)
    if result["error"]:
        answer = f"查询执行失败：{result['error']}"
        _log(session_id, user_id, question, sql, "sql_error", 0, start)
        session_store.add_message(session_id, "user", question)
        session_store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "sql": sql, "data": [], "row_count": 0, "status": "sql_error", "session_id": session_id}

    # 4. 解释结果
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
