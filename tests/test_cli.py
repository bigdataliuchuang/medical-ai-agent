from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_agent.cli import _health_check
from ai_data_agent.config import ConfigError


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV_KEYS = [
    "DORIS_HOST",
    "DORIS_PORT",
    "DORIS_USER",
    "DORIS_PASSWORD",
    "DORIS_DATABASE",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "MILVUS_COLLECTION",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_DIMENSION",
]


def test_static_health_check_fails_without_required_production_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DATA_AGENT_ENV_FILE", str(tmp_path / "missing.env"))
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigError):
        _health_check(
            str(ROOT / "config" / "application.example.yaml"),
            str(ROOT / "metadata"),
            dynamic=False,
        )
