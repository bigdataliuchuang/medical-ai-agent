from __future__ import annotations

from pathlib import Path

from ai_data_agent.config import DataAgentConfig
from ai_data_agent.text2sql.factory import build_llm_client, build_sql_guard


ROOT = Path(__file__).resolve().parents[1]


def test_text2sql_factory_uses_default_base_url_when_optional_placeholder_unresolved(monkeypatch) -> None:
    monkeypatch.setenv("DORIS_HOST", "127.0.0.1")
    monkeypatch.setenv("DORIS_PORT", "9030")
    monkeypatch.setenv("DORIS_USER", "user")
    monkeypatch.setenv("DORIS_PASSWORD", "pass")
    monkeypatch.setenv("DORIS_DATABASE", "medical")
    monkeypatch.setenv("MILVUS_HOST", "127.0.0.1")
    monkeypatch.setenv("MILVUS_PORT", "19530")
    monkeypatch.setenv("MILVUS_COLLECTION", "medical_metadata")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-test")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1536")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    config = DataAgentConfig.load(
        ROOT / "config" / "application.example.yaml",
        env_file=ROOT / "missing.env",
    )

    assert build_llm_client(config).base_url == "https://api.openai.com/v1"
    assert build_sql_guard(config).allowed_schemas == {"dwd", "dim", "dws", "ads", "dq", "mpi", "mdm"}
