from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_agent.config import ConfigError, DataAgentConfig
from ai_data_agent.metadata import MetadataRepository


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


def test_metadata_repository_loads_curated_assets() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")

    assert repo.find_table("dwd.dwd_visit") is not None
    assert repo.find_metric("antitumor_drug_amount") is not None
    assert "dept_name" in repo.find_metric("antitumor_drug_amount")["dimensions"]
    assert any(rule["rule_code"] == "DQ-001" for rule in repo.dq_rules())
    assert any(rule["rule_code"] == "DQ-DRUG-DEPT-NULL" for rule in repo.dq_rules())


def test_example_config_fails_fast_without_production_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config = DataAgentConfig.load(
        ROOT / "config" / "application.example.yaml",
        env_file=tmp_path / "missing.env",
    )

    with pytest.raises(ConfigError):
        config.validate_startup_requirements()


def test_config_loads_env_file_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "DORIS_HOST",
        "DORIS_PORT",
        "DORIS_USER",
        "DORIS_PASSWORD",
        "DORIS_DATABASE",
    ]:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DORIS_HOST=127.0.0.1",
                "DORIS_PORT=9030",
                "DORIS_USER=root",
                "DORIS_PASSWORD=secret",
                "DORIS_DATABASE=medical_dw",
            ]
        ),
        encoding="utf-8",
    )
    config_file = tmp_path / "application.yaml"
    config_file.write_text(
        """
doris:
  host: ${DORIS_HOST}
  port: ${DORIS_PORT}
  user: ${DORIS_USER}
  password: ${DORIS_PASSWORD}
  database: ${DORIS_DATABASE}
""",
        encoding="utf-8",
    )

    config = DataAgentConfig.load(config_file, env_file=env_file)

    assert config.require("doris.host") == "127.0.0.1"
    assert config.require("doris.password") == "secret"
