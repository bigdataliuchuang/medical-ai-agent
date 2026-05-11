"""Text-to-SQL generation service with mandatory SQL Guard validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ai_data_agent.graphrag.context_builder import TextToSqlContext
from ai_data_agent.text2sql.llm import LlmClient
from ai_data_agent.text2sql.prompt_builder import build_sql_repair_prompt, build_text_to_sql_prompt
from ai_data_agent.text2sql.sql_guard import SqlGuardResult


class SqlGenerationError(RuntimeError):
    """Raised when generated SQL is missing or rejected."""


class SqlValidator(Protocol):
    def validate(self, sql: str) -> SqlGuardResult:
        """Validate generated SQL."""


@dataclass(frozen=True)
class SqlGenerationResult:
    sql: str
    prompt: str
    raw_response: str
    guard_result: SqlGuardResult


class SqlGenerationService:
    def __init__(self, llm: LlmClient, guard: SqlValidator):
        self.llm = llm
        self.guard = guard

    def generate(self, context: TextToSqlContext) -> SqlGenerationResult:
        prompt = build_text_to_sql_prompt(context)
        raw_response = self.llm.complete(prompt)
        sql = extract_sql(raw_response)
        guard_result = self.guard.validate(sql)
        if not guard_result.allowed:
            repair_prompt = build_sql_repair_prompt(sql, guard_result.reasons, context)
            raw_response = self.llm.complete(repair_prompt)
            sql = extract_sql(raw_response)
            guard_result = self.guard.validate(sql)
            if not guard_result.allowed:
                raise SqlGenerationError("; ".join(guard_result.reasons))
        return SqlGenerationResult(sql=sql, prompt=prompt, raw_response=raw_response, guard_result=guard_result)


def extract_sql(text: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    sql = fenced.group(1) if fenced else text
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()
    if not sql:
        raise SqlGenerationError("LLM response did not contain SQL.")
    return sql
