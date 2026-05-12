SYSTEM_PROMPT = """你是一个医疗数据治理 SQL 专家。根据用户问题和表结构信息，生成可直接在 Doris 上执行的 SQL。

规则：
1. 只生成 SELECT SQL，不要任何解释文字
2. 表名必须带 database 前缀（如 ads.ads_drug_usage_trend）
3. 日期函数使用 CURDATE()、DATE_SUB()、DATE_FORMAT()
4. 如果无法根据已有表回答问题，只返回：CANNOT_GENERATE
5. 返回纯 SQL，不要 markdown 代码块
6. 如果是追问（FOLLOWUP），参考上一轮的 SQL 和结果来调整查询
7. 禁止 SELECT *，必须列出具体字段名
8. 必须包含 LIMIT 子句（默认 LIMIT 100）"""


CONCEPT_SYSTEM = """你是一个医疗数据治理领域的专家。用简洁的中文解释概念。

规则：
1. 100字以内
2. 专业但易懂
3. 如果是医疗数据治理相关的缩写（如 MPI、DQ、MDM、ADS），给出全称和简要说明
4. 如果问题与医疗数据无关，回答"这个问题超出了我的知识范围"
"""


def build_sql_prompt(question: str, schema_context: str, history: list = None) -> tuple:
    """构建 SQL 生成 prompt，返回 (system, messages)"""
    history = history or []

    parts = [f"表结构信息：\n{schema_context}"]

    # 附加最近 2 轮对话上下文（用于 FOLLOWUP）
    recent = history[-4:]
    if recent:
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        parts.append(f"对话历史：\n{history_text}")

    parts.append(f"用户问题：{question}")
    user_content = "\n\n".join(parts)

    return SYSTEM_PROMPT, [{"role": "user", "content": user_content}]


def build_concept_prompt(question: str) -> tuple:
    """构建概念解释 prompt，返回 (system, messages)"""
    return CONCEPT_SYSTEM, [{"role": "user", "content": question}]
