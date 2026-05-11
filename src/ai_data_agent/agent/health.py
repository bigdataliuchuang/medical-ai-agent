"""Startup health validation for production dependencies."""

from __future__ import annotations

from ai_data_agent.config import DataAgentConfig
from ai_data_agent.executor.doris import DorisExecutor
from ai_data_agent.executor.duckdb import DuckDBExecutor
from ai_data_agent.graphrag.factory import build_embedding_client, build_milvus_store
from ai_data_agent.metadata import MetadataRepository


class HealthCheckError(RuntimeError):
    """Raised when startup validation fails."""


def validate_static_startup(config: DataAgentConfig, metadata: MetadataRepository) -> None:
    """Validate static startup requirements that do not open network connections."""

    config.validate_startup_requirements()
    if not metadata.tables():
        raise HealthCheckError("schema_catalog.yaml has no tables.")
    if not metadata.metrics():
        raise HealthCheckError("metric_catalog.yaml has no metrics.")
    if not metadata.dq_rules():
        raise HealthCheckError("dq_rule_catalog.yaml has no rules.")


def validate_dynamic_startup(config: DataAgentConfig, metadata: MetadataRepository) -> None:
    """Validate startup requirements that open production network connections."""

    validate_static_startup(config, metadata)
    try:
        build_milvus_store(config, create_if_missing=False)
        embedding = build_embedding_client(config)
        embedding.embed_texts(["health check"])
        executor_type = str(config.raw.get("executor", {}).get("type", "doris")).lower()
        if executor_type == "duckdb":
            DuckDBExecutor(database_path=str(config.require("duckdb.database_path"))).ping()
        else:
            DorisExecutor(
                host=str(config.require("doris.host")),
                port=int(config.require("doris.port")),
                user=str(config.require("doris.user")),
                password=str(config.require("doris.password")),
                database=str(config.require("doris.database")),
            ).ping()
    except Exception as exc:
        raise HealthCheckError(f"Dynamic startup health check failed: {exc}") from exc
