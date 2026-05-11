"""Factories for production Text-to-SQL services."""

from __future__ import annotations

from ai_data_agent.config import DataAgentConfig
from ai_data_agent.text2sql.generator import SqlGenerationService
from ai_data_agent.text2sql.llm import OpenAICompatibleLlmClient
from ai_data_agent.text2sql.sql_guard import SqlGuard


def build_llm_client(config: DataAgentConfig) -> OpenAICompatibleLlmClient:
    provider = str(config.require("llm.provider")).lower()
    if provider not in {"openai", "openai-compatible"}:
        raise ValueError(f"Unsupported LLM provider for current production factory: {provider}")
    return OpenAICompatibleLlmClient(
        base_url=_optional_value(config.raw.get("llm", {}).get("base_url"), "https://api.openai.com/v1"),
        api_key=str(config.require("llm.api_key")),
        model=str(config.require("llm.model")),
    )


def build_sql_guard(config: DataAgentConfig) -> SqlGuard:
    sql_guard_config = config.raw.get("sql_guard", {})
    return SqlGuard(
        allowed_schemas=sql_guard_config.get("allowed_schemas", []),
        deny_select_star=bool(sql_guard_config.get("deny_select_star", True)),
        require_limit_for_detail_query=bool(sql_guard_config.get("require_limit_for_detail_query", True)),
    )


def build_sql_generation_service(config: DataAgentConfig) -> SqlGenerationService:
    return SqlGenerationService(build_llm_client(config), build_sql_guard(config))


def _optional_value(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    if text.startswith("${") and text.endswith("}"):
        return default
    return text
