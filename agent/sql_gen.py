import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # anthropic | openai
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# ── 统一 LLM 调用入口（同步 + 异步）────────────────────────────────────────────

if LLM_PROVIDER == "openai":
    from openai import OpenAI, AsyncOpenAI
    _client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        timeout=LLM_TIMEOUT,
    )
    _async_client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        timeout=LLM_TIMEOUT,
    )

    def _call_llm(system: str, messages: list) -> str:
        resp = _client.chat.completions.create(
            model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "system", "content": system}] + messages,
        )
        return resp.choices[0].message.content.strip()

    async def _call_llm_async(system: str, messages: list) -> str:
        resp = await _async_client.chat.completions.create(
            model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "system", "content": system}] + messages,
        )
        return resp.choices[0].message.content.strip()

else:  # anthropic（默认）
    from anthropic import Anthropic, AsyncAnthropic
    _client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    _async_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def _call_llm(system: str, messages: list) -> str:
        resp = _client.messages.create(
            model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS,
            system=system, messages=messages, timeout=LLM_TIMEOUT,
        )
        return resp.content[0].text.strip()

    async def _call_llm_async(system: str, messages: list) -> str:
        resp = await _async_client.messages.create(
            model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS,
            system=system, messages=messages, timeout=LLM_TIMEOUT,
        )
        return resp.content[0].text.strip()


def _strip_markdown(text: str) -> str:
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


# ── System Prompts ─────────────────────────────────────────────────────────────

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

REPAIR_SYSTEM = """你是一个 Doris SQL 调试专家。给定原始问题、失败的 SQL 和错误信息，修正 SQL 使其能正确执行。

规则：
1. 只返回修正后的 SQL，不要解释
2. 保持原始查询意图不变
3. 如果无法修复，返回：CANNOT_REPAIR
4. 不要 markdown 代码块"""


# ── 同步接口（保持兼容）────────────────────────────────────────────────────────

def generate_sql_with_prompt(system_msg: str, messages: list) -> str:
    try:
        return _strip_markdown(_call_llm(system_msg, messages))
    except Exception:
        return "CANNOT_GENERATE"


def repair_sql(question: str, sql: str, error: str, schema_context: str) -> str:
    prompt = (
        f"表结构：\n{schema_context}\n\n"
        f"用户问题：{question}\n\n"
        f"失败的 SQL：\n{sql}\n\n"
        f"错误信息：\n{error}"
    )
    try:
        return _strip_markdown(_call_llm(REPAIR_SYSTEM, [{"role": "user", "content": prompt}]))
    except Exception:
        return "CANNOT_REPAIR"


def explain_concept(question: str) -> str:
    try:
        return _call_llm(CONCEPT_SYSTEM, [{"role": "user", "content": question}])
    except Exception:
        return "概念解释生成失败，请稍后重试。"


def explain_result(question: str, sql: str, data: list) -> str:
    data_str = str(data[:10]) if data else "[]"
    prompt = f"问题：{question}\nSQL：{sql}\n查询结果（前10条）：{data_str}"
    try:
        return _call_llm(EXPLAIN_SYSTEM, [{"role": "user", "content": prompt}])
    except Exception:
        return "结果解释生成失败，请查看原始数据。"


# ── 异步接口 ──────────────────────────────────────────────────────────────────

async def generate_sql_with_prompt_async(system_msg: str, messages: list) -> str:
    try:
        return _strip_markdown(await _call_llm_async(system_msg, messages))
    except Exception:
        return "CANNOT_GENERATE"


async def repair_sql_async(question: str, sql: str, error: str, schema_context: str) -> str:
    prompt = (
        f"表结构：\n{schema_context}\n\n"
        f"用户问题：{question}\n\n"
        f"失败的 SQL：\n{sql}\n\n"
        f"错误信息：\n{error}"
    )
    try:
        return _strip_markdown(await _call_llm_async(REPAIR_SYSTEM, [{"role": "user", "content": prompt}]))
    except Exception:
        return "CANNOT_REPAIR"


async def explain_concept_async(question: str) -> str:
    try:
        return await _call_llm_async(CONCEPT_SYSTEM, [{"role": "user", "content": question}])
    except Exception:
        return "概念解释生成失败，请稍后重试。"


async def explain_result_async(question: str, sql: str, data: list) -> str:
    data_str = str(data[:10]) if data else "[]"
    prompt = f"问题：{question}\nSQL：{sql}\n查询结果（前10条）：{data_str}"
    try:
        return await _call_llm_async(EXPLAIN_SYSTEM, [{"role": "user", "content": prompt}])
    except Exception:
        return "结果解释生成失败，请查看原始数据。"
