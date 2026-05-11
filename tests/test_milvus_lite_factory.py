"""Tests for Milvus Lite factory wiring."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from ai_data_agent.config import DataAgentConfig
from ai_data_agent.graphrag.factory import build_milvus_store


def test_build_milvus_store_supports_lite_mode(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeMilvusClient:
        def __init__(self, uri: str):
            captured["uri"] = uri

        def has_collection(self, collection_name: str) -> bool:
            return True

    fake_pymilvus = types.SimpleNamespace(MilvusClient=FakeMilvusClient)
    monkeypatch.setitem(sys.modules, "pymilvus", fake_pymilvus)

    config_file = tmp_path / "application.pocket.yaml"
    config_file.write_text(
        f"""
executor:
  type: duckdb
duckdb:
  database_path: {tmp_path / "medical_dw.db"}
milvus:
  mode: lite
  uri: {tmp_path / "medical_metadata.db"}
  collection: medical_metadata
llm:
  provider: openai-compatible
  model: qwen-plus
  api_key: sk-test
embedding:
  provider: openai-compatible
  model: text-embedding-v3
  api_key: sk-test
  dimension: 3
""",
        encoding="utf-8",
    )

    store = build_milvus_store(DataAgentConfig.load(config_file))

    assert captured["uri"] == str(tmp_path / "medical_metadata.db")
    assert store.collection.collection_name == "medical_metadata"
