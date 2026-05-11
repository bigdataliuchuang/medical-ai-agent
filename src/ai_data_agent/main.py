"""Uvicorn entrypoint — reads config from environment variables."""

from __future__ import annotations

import os

from ai_data_agent.api.app import create_app

config_path = os.environ.get("AI_DATA_AGENT_CONFIG", "config/application.local.yaml")
metadata_root = os.environ.get("AI_DATA_AGENT_METADATA_ROOT", "metadata")

app = create_app(config_path=config_path, metadata_root=metadata_root)
