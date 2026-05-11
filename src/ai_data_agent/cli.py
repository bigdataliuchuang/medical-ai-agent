"""Command-line entry points for production operations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_data_agent.agent.health import HealthCheckError, validate_dynamic_startup, validate_static_startup
from ai_data_agent.config import DataAgentConfig
from ai_data_agent.graphrag.factory import build_embedding_client, build_milvus_store
from ai_data_agent.graphrag.ingest import MetadataIngestionService
from ai_data_agent.graphrag.milvus_store import MilvusStoreError
from ai_data_agent.metadata import MetadataRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-data-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest-metadata", help="Ingest curated metadata into Milvus")
    ingest.add_argument("--config", required=True, help="Path to production config YAML")
    ingest.add_argument("--metadata-root", default="ai-data-agent/metadata", help="Path to metadata YAML directory")
    ingest.add_argument(
        "--create-collection",
        action="store_true",
        help="Create the Milvus collection if it does not exist. Use only in controlled setup.",
    )

    health = subcommands.add_parser("health-check", help="Validate startup requirements")
    health.add_argument("--config", required=True, help="Path to production config YAML")
    health.add_argument("--metadata-root", default="ai-data-agent/metadata", help="Path to metadata YAML directory")
    health.add_argument(
        "--dynamic",
        action="store_true",
        help="Open production network connections to Doris, Milvus, and embedding service.",
    )

    serve = subcommands.add_parser("serve", help="Start the FastAPI Agent API server")
    serve.add_argument("--config", required=True, help="Path to production config YAML")
    serve.add_argument("--metadata-root", default="ai-data-agent/metadata", help="Path to metadata YAML directory")
    serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")

    evaluate = subcommands.add_parser("evaluate", help="Run batch evaluation against the question set")
    evaluate.add_argument("--config", required=True, help="Path to production config YAML")
    evaluate.add_argument("--metadata-root", default="ai-data-agent/metadata", help="Path to metadata YAML directory")
    evaluate.add_argument("--questions", default="ai-data-agent/evaluation/questions.jsonl", help="Path to questions JSONL")
    evaluate.add_argument("--output", default=None, help="Write JSON report to this path")
    evaluate.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate SQL only, skip Doris execution.",
    )

    args = parser.parse_args()
    try:
        if args.command == "ingest-metadata":
            return _ingest_metadata(args.config, args.metadata_root, args.create_collection)
        if args.command == "health-check":
            return _health_check(args.config, args.metadata_root, args.dynamic)
        if args.command == "serve":
            return _serve(args.config, args.metadata_root, args.host, args.port)
        if args.command == "evaluate":
            return _evaluate(args.config, args.metadata_root, args.questions, args.output, args.dry_run)
        raise AssertionError(f"Unhandled command: {args.command}")
    except (HealthCheckError, MilvusStoreError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _ingest_metadata(config_path: str, metadata_root: str, create_collection: bool) -> int:
    config = DataAgentConfig.load(config_path)
    config.validate_startup_requirements()
    repository = MetadataRepository.load(Path(metadata_root))
    embedding = build_embedding_client(config)
    store = build_milvus_store(config, create_if_missing=create_collection)
    report = MetadataIngestionService(repository, embedding, store).ingest()
    print(f"ingested_chunks={report.inserted_count} total_chunks={report.chunk_count}")
    return 0


def _health_check(config_path: str, metadata_root: str, dynamic: bool) -> int:
    config = DataAgentConfig.load(config_path)
    repository = MetadataRepository.load(Path(metadata_root))
    if dynamic:
        validate_dynamic_startup(config, repository)
        print("dynamic_health_check=ok")
    else:
        validate_static_startup(config, repository)
        print("static_health_check=ok")
    return 0


def _serve(config_path: str, metadata_root: str, host: str, port: int) -> int:
    import uvicorn

    from ai_data_agent.api.app import create_app

    app = create_app(config_path, metadata_root)
    uvicorn.run(app, host=host, port=port)
    return 0


def _evaluate(config_path: str, metadata_root: str, questions_path: str, output: str | None, dry_run: bool) -> int:
    import json
    import time

    from ai_data_agent.evaluation.runner import EvalResult, build_report, evaluate_question, load_questions
    from ai_data_agent.graphrag.context_builder import GraphRagContextBuilder
    from ai_data_agent.graphrag.factory import build_embedding_client, build_milvus_store
    from ai_data_agent.graphrag.graph import SchemaGraphRetriever
    from ai_data_agent.graphrag.retriever import GraphRagRetriever
    from ai_data_agent.semantic_layer.metrics import MetricResolver
    from ai_data_agent.text2sql.factory import build_sql_generation_service

    config = DataAgentConfig.load(config_path)
    config.validate_startup_requirements()
    metadata = MetadataRepository.load(Path(metadata_root))
    questions = load_questions(questions_path)

    embedding = build_embedding_client(config)
    store = build_milvus_store(config)
    graph_retriever = SchemaGraphRetriever(metadata.schema_graph, metadata.lineage_graph)
    retriever = GraphRagRetriever(embedding, store, graph_retriever)
    metric_resolver = MetricResolver(metadata.metric_catalog)
    context_builder = GraphRagContextBuilder(metadata, graph_retriever, metric_resolver)
    sql_generator = build_sql_generation_service(config)

    query_executor = None
    if not dry_run:
        from ai_data_agent.api.deps import _build_query_executor

        query_executor = _build_query_executor(config)

    results: list[EvalResult] = []
    for i, question in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {question.id}: {question.question}", file=sys.stderr)
        started = time.monotonic()
        sql = ""
        error: str | None = None
        context_tables: list[str] = []
        context_metrics: list[str] = []
        context_dq_rules: list[str] = []

        try:
            retrieval = retriever.search_metadata(question.question, top_k=5)
            context = context_builder.build(retrieval)
            context_tables = [t.name for t in context.tables]
            context_metrics = [m.name for m in context.metrics]
            context_dq_rules = [r.rule_code for r in context.dq_rules]

            sql_result = sql_generator.generate(context)
            sql = sql_result.sql

            if query_executor:
                query_executor.execute(sql)
        except Exception as exc:
            error = str(exc)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        result = evaluate_question(
            question=question,
            sql=sql,
            context_tables=context_tables,
            context_metrics=context_metrics,
            context_dq_rules=context_dq_rules,
            elapsed_ms=elapsed_ms,
            error=error,
        )
        results.append(result)

    report = build_report(results)
    print("\n" + report.summary_table(), file=sys.stderr)

    if output:
        Path(output).write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written to {output}", file=sys.stderr)

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
