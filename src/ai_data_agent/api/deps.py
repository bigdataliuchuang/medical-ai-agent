"""FastAPI dependency injection for wiring query services."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ai_data_agent.agent.audit import AuditLogger, DorisAuditLogger, NoopAuditLogger
from ai_data_agent.agent.loop import ReActAgent
from ai_data_agent.agent.result_analyzer import ResultAnalyzer
from ai_data_agent.agent.tools import ToolRegistry
from ai_data_agent.config import DataAgentConfig
from ai_data_agent.executor.doris import DorisExecutor
from ai_data_agent.executor.duckdb import DuckDBExecutor
from ai_data_agent.graphrag.context_builder import GraphRagContextBuilder
from ai_data_agent.graphrag.factory import build_embedding_client, build_milvus_store
from ai_data_agent.graphrag.graph import SchemaGraphRetriever
from ai_data_agent.graphrag.retriever import GraphRagRetriever
from ai_data_agent.metadata import MetadataRepository
from ai_data_agent.semantic_layer.metrics import MetricResolver
from ai_data_agent.text2sql.factory import build_sql_generation_service
from ai_data_agent.text2sql.generator import SqlGenerationService
from ai_data_agent.text2sql.factory import build_llm_client
from ai_data_agent.text2sql.sql_guard import SqlGuard


@dataclass(frozen=True)
class QueryServices:
    retriever: GraphRagRetriever
    context_builder: GraphRagContextBuilder
    sql_generator: SqlGenerationService
    query_executor: DorisExecutor | DuckDBExecutor
    doris_executor: DorisExecutor | DuckDBExecutor
    result_analyzer: ResultAnalyzer
    audit_logger: AuditLogger
    agent: ReActAgent


def get_config(request: Request) -> DataAgentConfig:
    return request.app.state.config


def get_metadata(request: Request) -> MetadataRepository:
    return request.app.state.metadata


def get_query_services(request: Request) -> QueryServices:
    return request.app.state.query_services


def get_memory(request: Request):
    return request.app.state.memory


def build_query_services(
    config: DataAgentConfig,
    metadata: MetadataRepository,
) -> QueryServices:
    embedding = build_embedding_client(config)
    store = build_milvus_store(config)
    graph_retriever = SchemaGraphRetriever(
        metadata.schema_graph, metadata.lineage_graph
    )

    retriever = GraphRagRetriever(embedding, store, graph_retriever)
    metric_resolver = MetricResolver(metadata.metric_catalog)
    context_builder = GraphRagContextBuilder(metadata, graph_retriever, metric_resolver)
    sql_generator = build_sql_generation_service(config)
    result_analyzer = ResultAnalyzer(build_llm_client(config))

    query_executor = _build_query_executor(config)
    audit_logger = _build_audit_logger(config)

    # Build agent with tool registry
    agent = _build_agent(config, retriever, context_builder, sql_generator, query_executor, result_analyzer)

    return QueryServices(
        retriever=retriever,
        context_builder=context_builder,
        sql_generator=sql_generator,
        query_executor=query_executor,
        doris_executor=query_executor,
        result_analyzer=result_analyzer,
        audit_logger=audit_logger,
        agent=agent,
    )


def _build_query_executor(config: DataAgentConfig) -> DorisExecutor | DuckDBExecutor:
    executor_type = str(config.raw.get("executor", {}).get("type", "doris")).lower()
    if executor_type == "duckdb":
        duckdb_cfg = config.raw.get("duckdb", {})
        return DuckDBExecutor(
            database_path=str(duckdb_cfg.get("database_path", "data/medical_dw.db")),
            read_only=bool(duckdb_cfg.get("read_only", False)),
        )
    if executor_type != "doris":
        raise ValueError(f"Unsupported executor type: {executor_type}")

    doris_cfg = config.raw["doris"]
    return DorisExecutor(
        host=doris_cfg["host"],
        port=doris_cfg["port"],
        user=doris_cfg["user"],
        password=doris_cfg["password"],
        database=doris_cfg["database"],
    )


def _build_audit_logger(config: DataAgentConfig) -> AuditLogger:
    audit_cfg = config.raw.get("audit", {})
    if str(audit_cfg.get("sink", "doris")).lower() in {"none", "noop", "disabled"}:
        return NoopAuditLogger()

    doris_cfg = config.raw["doris"]
    return DorisAuditLogger(
        host=doris_cfg["host"],
        port=doris_cfg["port"],
        user=doris_cfg["user"],
        password=doris_cfg["password"],
        database=doris_cfg["database"],
        table=audit_cfg.get("table", "dq.ai_data_agent_audit_log"),
    )


def _build_agent(
    config: DataAgentConfig,
    retriever: GraphRagRetriever,
    context_builder: GraphRagContextBuilder,
    sql_generator: SqlGenerationService,
    doris_executor: DorisExecutor | DuckDBExecutor,
    result_analyzer: ResultAnalyzer,
) -> ReActAgent:
    from ai_data_agent.agent.tool_impls import (
        AnalyzeResultTool,
        ExecuteSqlTool,
        GenerateSqlFromContextTool,
        SearchMetadataTool,
        ValidateSqlTool,
    )

    registry = ToolRegistry()
    registry.register(SearchMetadataTool(retriever, context_builder))
    registry.register(GenerateSqlFromContextTool(sql_generator))

    sql_guard_config = config.raw.get("sql_guard", {})
    guard = SqlGuard(
        allowed_schemas=sql_guard_config.get("allowed_schemas", []),
        deny_select_star=bool(sql_guard_config.get("deny_select_star", True)),
        require_limit_for_detail_query=bool(sql_guard_config.get("require_limit_for_detail_query", True)),
    )
    registry.register(ValidateSqlTool(guard))
    registry.register(ExecuteSqlTool(doris_executor))
    registry.register(AnalyzeResultTool(result_analyzer))

    agent_config = config.raw.get("agent", {})
    max_steps = int(agent_config.get("max_steps", 8))

    llm = build_llm_client(config)
    return ReActAgent(llm=llm, tools=registry, max_steps=max_steps)
