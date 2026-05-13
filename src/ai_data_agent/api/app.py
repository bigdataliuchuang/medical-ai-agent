"""FastAPI application factory and route definitions."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ai_data_agent.agent.audit import AuditRecord
from ai_data_agent.agent.loop import AgentTrace
from ai_data_agent.agent.memory import ConversationMemory
from ai_data_agent.api.deps import (
    QueryServices,
    build_query_services,
    get_config,
    get_memory,
    get_metadata,
    get_query_services,
)
from ai_data_agent.api.models import (
    AgentQueryRequest,
    AgentQueryResponse,
    AgentStepResponse,
    ContextSummary,
    ConversationTurnResponse,
    HealthResponse,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
    SessionDeleteResponse,
    SessionHistoryResponse,
)
from ai_data_agent.config import DataAgentConfig
from ai_data_agent.executor.doris import DorisExecutionError
from ai_data_agent.metadata import MetadataRepository
from ai_data_agent.semantic_service.api import router as semantic_router
from ai_data_agent.semantic_service.audit import SQLiteSemanticAuditStore
from ai_data_agent.semantic_service.catalog import SemanticCatalog
from ai_data_agent.semantic_service.governance import SQLiteSemanticGovernanceStore
from ai_data_agent.semantic_service.service import SemanticLayerService
from ai_data_agent.text2sql.generator import SqlGenerationError

logger = logging.getLogger(__name__)


_QUERY_CONSOLE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>医疗数据 Agent</title>
  <style>
    :root { color-scheme: light; --ink: #1d2630; --muted: #667085; --line: #d8dee7; --brand: #0f766e; --bg: #f6f8fb; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }
    header { padding: 28px 32px 18px; background: #fff; border-bottom: 1px solid var(--line); }
    main { max-width: 1120px; margin: 0 auto; padding: 24px 32px 48px; }
    h1 { margin: 0 0 8px; font-size: 24px; font-weight: 700; letter-spacing: 0; }
    p { margin: 0; color: var(--muted); line-height: 1.6; }
    form { display: grid; grid-template-columns: 1fr auto; gap: 12px; margin: 20px 0; }
    textarea { width: 100%; min-height: 88px; resize: vertical; padding: 14px; border: 1px solid var(--line); border-radius: 8px; font: inherit; line-height: 1.5; background: #fff; }
    button { height: 44px; padding: 0 18px; border: 0; border-radius: 8px; background: var(--brand); color: #fff; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .quick { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
    .quick button { height: 34px; background: #e6f4f1; color: #0f5f59; font-weight: 600; }
    section { margin-top: 16px; padding: 18px; background: #fff; border: 1px solid var(--line); border-radius: 8px; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.5; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 700; background: #f9fafb; }
    .grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
    .error { border-color: #f3b7b7; background: #fff7f7; color: #9f1d1d; }
    @media (max-width: 720px) { main, header { padding-left: 16px; padding-right: 16px; } form { grid-template-columns: 1fr; } button { width: 100%; } }
  </style>
</head>
<body>
  <header>
    <h1>医疗数据 Agent</h1>
    <p>本地口袋版：自然语言生成 SQL，查询 DuckDB 医疗样例数仓，并返回业务解释。</p>
  </header>
  <main>
    <form id="query-form">
      <textarea id="question" aria-label="查询问题">各科室抗肿瘤药物费用排名，显示科室名称</textarea>
      <button id="submit" type="submit">查询</button>
    </form>
    <div class="quick">
      <button type="button" data-question="各科室抗肿瘤药物费用排名，显示科室名称">科室费用排名</button>
      <button type="button" data-question="查询抗肿瘤药物汇总中科室缺失的数据质量问题，返回规则编码、药品名称、科室编码、科室名称、问题原因和问题数量">科室缺失 DQ</button>
      <button type="button" data-question="按药品名称统计抗肿瘤药物费用排名">药品费用排名</button>
    </div>
    <div id="status"></div>
    <div id="result" class="grid"></div>
  </main>
  <script>
    const form = document.querySelector("#query-form");
    const question = document.querySelector("#question");
    const submit = document.querySelector("#submit");
    const statusBox = document.querySelector("#status");
    const result = document.querySelector("#result");

    document.querySelectorAll("[data-question]").forEach((button) => {
      button.addEventListener("click", () => {
        question.value = button.dataset.question;
        form.requestSubmit();
      });
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      statusBox.innerHTML = "<section><p>查询中...</p></section>";
      result.innerHTML = "";
      try {
        const response = await fetch("/api/v1/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: question.value, top_k: 5, max_rows: 20 })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "查询失败");
        statusBox.innerHTML = "";
        renderResult(payload);
      } catch (error) {
        statusBox.innerHTML = `<section class="error"><strong>查询失败</strong><p>${escapeHtml(error.message)}</p></section>`;
      } finally {
        submit.disabled = false;
      }
    });

    function renderResult(data) {
      result.innerHTML = [
        section("SQL", `<pre>${escapeHtml(data.sql)}</pre>`),
        section("结果", renderTable(data.columns, data.rows)),
        section("解释", `<pre>${escapeHtml(data.answer)}</pre>`),
        section("上下文", `<pre>${escapeHtml(JSON.stringify(data.context_summary, null, 2))}</pre>`)
      ].join("");
    }

    function section(title, body) {
      return `<section><h2>${title}</h2>${body}</section>`;
    }

    function renderTable(columns, rows) {
      if (!rows.length) return "<p>无结果</p>";
      const head = columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
      const body = rows.map((row) => `<tr>${columns.map((c) => `<td>${escapeHtml(row[c] ?? "NULL")}</td>`).join("")}</tr>`).join("");
      return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }
  </script>
</body>
</html>
"""


def create_app(config_path: str, metadata_root: str = "ai-data-agent/metadata") -> FastAPI:
    app = FastAPI(
        title="Medical Data Agent",
        description="生产级医疗数据治理智能分析 Data Agent",
        version="0.1.0",
    )

    config = DataAgentConfig.load(config_path)
    config.validate_startup_requirements()
    metadata = MetadataRepository.load(Path(metadata_root))

    app.state.config = config
    app.state.metadata = metadata
    app.state.query_services = build_query_services(config, metadata)
    app.state.memory = ConversationMemory()
    semantic_catalog = SemanticCatalog.load(Path(metadata_root) / "semantic")
    semantic_audit_path = os.getenv("SEMANTIC_AUDIT_DB_PATH", "data/semantic_audit.db")
    app.state.semantic_service = SemanticLayerService(
        semantic_catalog,
        query_executor=app.state.query_services.query_executor,
        audit_store=SQLiteSemanticAuditStore(semantic_audit_path),
        governance_store=SQLiteSemanticGovernanceStore(semantic_audit_path),
    )
    # In-process counters for /metrics
    app.state.metrics = {
        "total_queries": 0,
        "total_agent_queries": 0,
        "total_errors": 0,
        "elapsed_sum_ms": 0.0,
        "sql_guard_rejections": 0,
        "started_at": time.monotonic(),
    }

    app.get("/", response_class=HTMLResponse)(_home_endpoint)
    app.get("/favicon.ico", status_code=204)(_favicon_endpoint)
    app.post("/api/v1/query", response_model=QueryResponse)(_query_endpoint)
    app.post("/api/v1/agent/query", response_model=AgentQueryResponse)(_agent_query_endpoint)
    app.get("/api/v1/sessions/{session_id}/history", response_model=SessionHistoryResponse)(_session_history_endpoint)
    app.delete("/api/v1/sessions/{session_id}", response_model=SessionDeleteResponse)(_session_delete_endpoint)
    app.get("/health", response_model=HealthResponse)(_health_endpoint)
    app.get("/health/ready", response_model=HealthResponse)(_readiness_endpoint)
    app.get("/metrics", response_model=MetricsResponse)(_metrics_endpoint)
    app.include_router(semantic_router)

    return app


async def _home_endpoint() -> HTMLResponse:
    return HTMLResponse(_QUERY_CONSOLE_HTML)


async def _favicon_endpoint() -> Response:
    return Response(status_code=204)


async def _query_endpoint(
    request: QueryRequest,
    services: QueryServices = Depends(get_query_services),
) -> QueryResponse:
    request_id = str(uuid.uuid4())
    started = time.monotonic()
    sql = ""
    context = None

    try:
        retrieval = services.retriever.search_metadata(request.question, top_k=request.top_k)
    except Exception as exc:
        logger.exception("GraphRAG retrieval failed")
        _write_audit(
            services,
            AuditRecord(
                request_id=request_id,
                question=request.question,
                sql=sql,
                status="retrieval_failed",
                retrieved_sources=0,
                context_tables=[],
                context_metrics=[],
                context_dq_rules=[],
                row_count=0,
                elapsed_ms=_elapsed_ms(started),
                error_message=str(exc),
                answer_summary=None,
            ),
        )
        raise HTTPException(status_code=502, detail=f"Retrieval failed: {exc}") from exc

    context = services.context_builder.build(retrieval)

    try:
        sql_result = services.sql_generator.generate(context)
        sql = sql_result.sql
    except SqlGenerationError as exc:
        _write_audit(
            services,
            _audit_record(
                request_id=request_id,
                question=request.question,
                sql=sql,
                status="sql_rejected",
                context=context,
                row_count=0,
                elapsed_ms=_elapsed_ms(started),
                error_message=str(exc),
                answer_summary=None,
            ),
        )
        raise HTTPException(status_code=422, detail=f"SQL generation rejected: {exc}") from exc

    try:
        doris_result = services.doris_executor.execute(sql_result.sql)
    except DorisExecutionError as exc:
        _write_audit(
            services,
            _audit_record(
                request_id=request_id,
                question=request.question,
                sql=sql,
                status="doris_failed",
                context=context,
                row_count=0,
                elapsed_ms=_elapsed_ms(started),
                error_message=str(exc),
                answer_summary=None,
            ),
        )
        raise HTTPException(status_code=502, detail=f"Doris execution failed: {exc}") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    rows = doris_result.rows[: request.max_rows]
    analysis = services.result_analyzer.analyze(
        question=request.question,
        sql=sql_result.sql,
        query_result=doris_result,
        context=context,
    )
    _write_audit(
        services,
        _audit_record(
            request_id=request_id,
            question=request.question,
            sql=sql,
            status="success",
            context=context,
            row_count=len(rows),
            elapsed_ms=elapsed_ms,
            error_message=None,
            answer_summary=analysis.answer,
        ),
    )
    return QueryResponse(
        request_id=request_id,
        question=request.question,
        sql=sql_result.sql,
        columns=doris_result.columns,
        rows=rows,
        row_count=len(rows),
        elapsed_ms=elapsed_ms,
        answer=analysis.answer,
        downstream_suggestions=analysis.downstream_suggestions,
        context_summary=ContextSummary(
            tables=[t.name for t in context.tables],
            metrics=[m.name for m in context.metrics],
            dq_rules=[r.rule_code for r in context.dq_rules],
            join_paths=len(context.join_paths),
            sources_count=len(context.sources),
        ),
    )


async def _agent_query_endpoint(
    request: AgentQueryRequest,
    services: QueryServices = Depends(get_query_services),
    memory: ConversationMemory = Depends(get_memory),
) -> AgentQueryResponse:
    request_id = uuid.uuid4().hex[:16]
    session_id = request.session_id or uuid.uuid4().hex[:12]
    logger.info("Agent query started", extra={"request_id": request_id, "session_id": session_id, "question": request.question})

    history = memory.get_history(session_id, max_turns=5)

    try:
        trace = services.agent.run(
            question=request.question,
            request_id=request_id,
            conversation_history=history,
        )
    except Exception as exc:
        logger.exception("Agent execution failed")
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {exc}") from exc

    if trace.final_answer:
        memory.save_turn(
            session_id=session_id,
            question=request.question,
            answer=trace.final_answer,
            sql=trace.final_sql,
        )

    steps = [
        AgentStepResponse(
            step_number=s.step_number,
            thought=s.thought,
            action=s.action,
            action_input=s.action_input,
            observation=s.observation,
            is_final=s.is_final,
            elapsed_ms=s.elapsed_ms,
        )
        for s in trace.steps
    ]

    _write_audit(
        services,
        AuditRecord(
            request_id=request_id,
            question=request.question,
            sql=trace.final_sql or "",
            status=trace.status,
            retrieved_sources=0,
            context_tables=[],
            context_metrics=[],
            context_dq_rules=[],
            row_count=0,
            elapsed_ms=trace.total_elapsed_ms,
            error_message=None if trace.status == "success" else trace.status,
            answer_summary=trace.final_answer,
        ),
    )

    return AgentQueryResponse(
        request_id=request_id,
        session_id=session_id,
        question=request.question,
        sql=trace.final_sql,
        answer=trace.final_answer,
        status=trace.status,
        steps=steps,
        total_elapsed_ms=trace.total_elapsed_ms,
        total_llm_calls=trace.total_llm_calls,
    )


async def _session_history_endpoint(
    session_id: str,
    memory: ConversationMemory = Depends(get_memory),
) -> SessionHistoryResponse:
    turns = memory.get_history(session_id)
    return SessionHistoryResponse(
        session_id=session_id,
        turns=[
            ConversationTurnResponse(
                turn_number=t.turn_number,
                question=t.question,
                answer=t.answer,
                sql=t.sql,
                tables_used=t.tables_used,
                created_at=t.created_at,
            )
            for t in turns
        ],
    )


async def _session_delete_endpoint(
    session_id: str,
    memory: ConversationMemory = Depends(get_memory),
) -> SessionDeleteResponse:
    deleted = memory.clear_session(session_id)
    return SessionDeleteResponse(session_id=session_id, deleted_turns=deleted)


async def _health_endpoint(
    metadata: MetadataRepository = Depends(get_metadata),
    config: DataAgentConfig = Depends(get_config),
) -> HealthResponse:
    checks: dict[str, str] = {}

    # Metadata catalog
    try:
        tables = metadata.tables()
        checks["metadata_tables"] = f"ok ({len(tables)} tables)"
    except Exception as exc:
        checks["metadata_tables"] = f"fail: {exc}"

    # DuckDB (pocket mode)
    try:
        import duckdb as _duckdb
        conn = _duckdb.connect(":memory:")
        conn.execute("SELECT 1")
        conn.close()
        checks["duckdb"] = "ok"
    except Exception as exc:
        checks["duckdb"] = f"fail: {exc}"

    # SQLite session storage
    try:
        import sqlite3 as _sqlite3
        conn2 = _sqlite3.connect(":memory:")
        conn2.execute("SELECT sqlite_version()")
        conn2.close()
        checks["sqlite"] = "ok"
    except Exception as exc:
        checks["sqlite"] = f"fail: {exc}"

    # Milvus (optional — skip if not configured)
    milvus_uri = getattr(config, "milvus_uri", None)
    if milvus_uri:
        try:
            from pymilvus import MilvusClient as _MilvusClient
            client = _MilvusClient(uri=milvus_uri)
            client.close()
            checks["milvus"] = "ok"
        except Exception as exc:
            checks["milvus"] = f"fail: {exc}"
    else:
        checks["milvus"] = "skip (not configured)"

    status = "ok" if all(v.startswith(("ok", "skip")) for v in checks.values()) else "degraded"
    return HealthResponse(status=status, checks=checks)


async def _metrics_endpoint(
    request: "Request",
) -> MetricsResponse:
    m = request.app.state.metrics
    total = m["total_queries"] + m["total_agent_queries"]
    avg = m["elapsed_sum_ms"] / total if total > 0 else 0.0
    return MetricsResponse(
        total_queries=m["total_queries"],
        total_agent_queries=m["total_agent_queries"],
        total_errors=m["total_errors"],
        avg_elapsed_ms=round(avg, 1),
        sql_guard_rejections=m["sql_guard_rejections"],
        uptime_seconds=round(time.monotonic() - m["started_at"], 1),
    )


def _audit_record(
    request_id: str,
    question: str,
    sql: str,
    status: str,
    context,
    row_count: int,
    elapsed_ms: int,
    error_message: str | None,
    answer_summary: str | None,
) -> AuditRecord:
    return AuditRecord(
        request_id=request_id,
        question=question,
        sql=sql,
        status=status,
        retrieved_sources=len(context.sources),
        context_tables=[table.name for table in context.tables],
        context_metrics=[metric.name for metric in context.metrics],
        context_dq_rules=[rule.rule_code for rule in context.dq_rules],
        row_count=row_count,
        elapsed_ms=elapsed_ms,
        error_message=error_message,
        answer_summary=answer_summary,
    )


def _write_audit(services: QueryServices, record: AuditRecord) -> None:
    try:
        services.audit_logger.write(record)
    except Exception:
        logger.exception("Audit log write failed")


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def _readiness_endpoint(
    config: DataAgentConfig = Depends(get_config),
    metadata: MetadataRepository = Depends(get_metadata),
) -> HealthResponse:
    checks: dict[str, str] = {}

    checks["metadata_tables"] = f"ok ({len(metadata.tables())} tables)"
    checks["metadata_metrics"] = f"ok ({len(metadata.metrics())} metrics)"

    from ai_data_agent.agent.health import validate_dynamic_startup

    try:
        validate_dynamic_startup(config, metadata)
        checks["external_dependencies"] = "ok"
    except Exception as exc:
        checks["external_dependencies"] = f"fail: {exc}"

    status = "ok" if all(v.startswith("ok") for v in checks.values()) else "degraded"
    return HealthResponse(status=status, checks=checks)
