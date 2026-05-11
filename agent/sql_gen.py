import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))
timeout = int(os.getenv("LLM_TIMEOUT", "30"))

EXPLAIN_SYSTEM = """你是一个医疗数据分析师。根据用户问题、SQL 和查询结果，用简洁的中文回答。

规则：
1. 包含具体数字
2. 100字以内
3. 数据为空时如实告知"未查询到相关数据"
4. 语气专业但易懂"""

CONCEPT_SYSTEM = """你是一个医疗数据治理领域的专家。用简洁的中文解释概念。

规则：
1. 100字以内
2. 专业但易懂
3. 如果是医疗数据治理相关的缩写（如 MPI、DQ、MDM、ADS），给出全称和简要说明
4. 如果问题与医疗数据无关，回答"这个问题超出了我的知识范围""""


def generate_sql_with_prompt(system_msg: str, messages: list) -> str:
    """使用 prompt_builder 构建的 system 和 messages 生成 SQL"""
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_msg,
            messages=messages,
            timeout=timeout,
        )
        sql = resp.content[0].text.strip()
        if sql.startswith("```"):
            sql = sql.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return sql
    except Exception:
        return "CANNOT_GENERATE"


REPAIR_SYSTEM = """你是一个 Doris SQL 调试专家。给定原始问题、失败的 SQL 和错误信息，修正 SQL 使其能正确执行。

规则：
1. 只返回修正后的 SQL，不要解释
2. 保持原始查询意图不变
3. 如果无法修复，返回：CANNOT_REPAIR
4. 不要 markdown 代码块"""


def repair_sql(question: str, sql: str, error: str, schema_context: str) -> str:
    """尝试自动修复执行失败的 SQL"""
    prompt = (
        f"表结构：\n{schema_context}\n\n"
        f"用户问题：{question}\n\n"
        f"失败的 SQL：\n{sql}\n\n"
        f"错误信息：\n{error}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=REPAIR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        fixed = resp.content[0].text.strip()
        if fixed.startswith("```"):
            fixed = fixed.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return fixed
    except Exception:
        return "CANNOT_REPAIR"


def explain_concept(question: str) -> str:
    """回答概念性问题，不生成 SQL"""
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=CONCEPT_SYSTEM,
            messages=[{"role": "user", "content": question}],
            timeout=timeout,
        )
        return resp.content[0].text.strip()
    except Exception:
        return "概念解释生成失败，请稍后重试。"


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
