"""Tests for local pocket-mode service wiring."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_data_agent.api.deps import build_query_services
from ai_data_agent.config import DataAgentConfig
from ai_data_agent.metadata import MetadataRepository

ROOT = Path(__file__).resolve().parents[1]


def test_build_query_services_uses_duckdb_executor_in_pocket_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "medical_dw.db"
    config_file = tmp_path / "application.pocket.yaml"
    config_file.write_text(
        f"""
executor:
  type: duckdb
duckdb:
  database_path: {database_path}
milvus:
  host: localhost
  port: 19530
  collection: test
llm:
  provider: openai-compatible
  base_url: http://localhost
  model: qwen-plus
  api_key: sk-test
embedding:
  provider: openai-compatible
  base_url: http://localhost
  model: text-embedding-v3
  api_key: sk-test
  dimension: 3
sql_guard:
  allowed_schemas: [ads, dws, dim, dq, mpi, mdm]
audit:
  sink: none
""",
        encoding="utf-8",
    )
    fake_duckdb = types.SimpleNamespace(connect=lambda path, read_only=False: MagicMock())
    monkeypatch.setitem(sys.modules, "duckdb", fake_duckdb)

    config = DataAgentConfig.load(config_file)
    metadata = MetadataRepository.load(ROOT / "metadata")

    with (
        patch("ai_data_agent.api.deps.build_embedding_client", return_value=MagicMock()),
        patch("ai_data_agent.api.deps.build_milvus_store", return_value=MagicMock()),
        patch("ai_data_agent.api.deps.build_sql_generation_service", return_value=MagicMock()),
        patch("ai_data_agent.api.deps.build_llm_client", return_value=MagicMock()),
    ):
        services = build_query_services(config, metadata)

    assert services.query_executor.database_path == str(database_path)
    assert services.doris_executor is services.query_executor
    services.audit_logger.write(MagicMock())
