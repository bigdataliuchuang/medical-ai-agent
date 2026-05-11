"""Configuration loading and fail-fast validation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


class ConfigError(RuntimeError):
    """Raised when production configuration is missing or invalid."""


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        _load_env_file_without_dependency(env_path)
        return
    load_dotenv(env_path, override=False)


def _load_env_file_without_dependency(env_path: Path) -> None:
    with env_path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def _default_env_file(config_path: Path) -> Path | None:
    configured = os.getenv("AI_DATA_AGENT_ENV_FILE")
    if configured:
        return Path(configured)
    candidates = [
        config_path.parent / ".env",
        config_path.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        match = PLACEHOLDER_PATTERN.match(value)
        if match:
            return os.getenv(match.group(1), value)
        return value
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item) for key, item in value.items()}
    return value


def _is_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PLACEHOLDER_PATTERN.match(value)) or value == ""
    return value is None


@dataclass(frozen=True)
class DataAgentConfig:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path, env_file: str | Path | None = None) -> "DataAgentConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        selected_env_file = Path(env_file) if env_file else _default_env_file(config_path)
        if selected_env_file:
            _load_env_file(selected_env_file)
        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        return cls(raw=_resolve_env_placeholders(raw))

    def require(self, dotted_key: str) -> Any:
        current: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                raise ConfigError(f"Missing required config: {dotted_key}")
            current = current[part]
        if _is_unresolved(current):
            raise ConfigError(f"Unresolved required config: {dotted_key}")
        return current

    def validate_startup_requirements(self) -> None:
        executor_type = str(self.raw.get("executor", {}).get("type", "doris")).lower()
        if executor_type == "duckdb":
            executor_required_keys = [
                "duckdb.database_path",
            ]
        elif executor_type == "doris":
            executor_required_keys = [
                "doris.host",
                "doris.port",
                "doris.user",
                "doris.password",
                "doris.database",
            ]
        else:
            raise ConfigError(f"Unsupported executor type: {executor_type}")

        milvus_mode = str(self.raw.get("milvus", {}).get("mode", "standalone")).lower()
        if milvus_mode == "lite":
            milvus_required_keys = [
                "milvus.uri",
                "milvus.collection",
            ]
        elif milvus_mode in {"standalone", "cluster", "remote"}:
            milvus_required_keys = [
                "milvus.host",
                "milvus.port",
                "milvus.collection",
            ]
        else:
            raise ConfigError(f"Unsupported milvus mode: {milvus_mode}")

        required_keys = [
            *executor_required_keys,
            *milvus_required_keys,
            "llm.provider",
            "llm.model",
            "llm.api_key",
            "embedding.provider",
            "embedding.model",
            "embedding.api_key",
            "embedding.dimension",
        ]
        for key in required_keys:
            self.require(key)
