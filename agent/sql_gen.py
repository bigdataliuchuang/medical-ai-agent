import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))
timeout = int(os.getenv("LLM_TIMEOUT", "30"))

SQL_SYSTEM = """你是一个 Doris SQL 专家。根据用户问题和表结构信息，生成可直接执行的 SQL。

规则：
1. 只生成 SELECT SQL，不要任何解释文字
2. 表名必须带 database 前缀（如 ads.ads_drug_usage_trend）
3. 日期函数使用 CURDATE()、DATE_SUB()、DATE_FORMAT()
4. 如果无法根据已有表回答问题，只返回：CANNOT_GENERATE
5. 返回纯 SQL，不要 markdown 代码块"""

EXPLAIN_SYSTEM = """你是一个医疗数据分析师。根据用户问题、SQL 和查询结果，用简洁的中文回答。

规则：
1. 包含具体数字
2. 100字以内
3. 数据为空时如实告知"未查询到相关数据"
4. 语气专业但易懂"""


def generate_sql(question: str, schema_context: str) -> str:
    prompt = f"表结构信息：\n{schema_context}\n\n用户问题：{question}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SQL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        sql = resp.content[0].text.strip()
        if sql.startswith("```"):
            sql = sql.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return sql
    except Exception:
        return "CANNOT_GENERATE"


def explain_result(question: str, sql: str, data: list) -> str:
    data_str = str(data[:10]) if data else "[]"
    prompt = f"问题：{question}\nSQL：{sql}\n查询结果（前10条）：{data_str}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=EXPLAIN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        return resp.content[0].text.strip()
    except Exception:
        return "结果解释生成失败，请查看原始数据。"
