"""Tests for the FastAPI Agent API endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_data_agent.agent.loop import AgentStep, AgentTrace
from ai_data_agent.agent.memory import ConversationMemory
from ai_data_agent.api.app import create_app
from ai_data_agent.executor.doris import DorisExecutionError, DorisQueryResult
from ai_data_agent.graphrag.context_builder import (
    DqRuleContext,
    MetricContext,
    TableContext,
    TextToSqlContext,
)
from ai_data_agent.graphrag.retriever import RetrievalContext
from ai_data_agent.text2sql.generator import SqlGenerationError, SqlGenerationResult
from ai_data_agent.text2sql.sql_guard import SqlGuardResult
from ai_data_agent.agent.result_analyzer import ResultAnalysis

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = str(ROOT / "config" / "application.example.yaml")
METADATA_ROOT = str(ROOT / "metadata")

MODULE_PREFIX = "ai_data_agent.api.app"


@pytest.fixture()
def mock_services():
    """Build mock QueryServices that bypass all external dependencies."""
    with (
        patch(f"{MODULE_PREFIX}.build_query_services") as mock_build,
        patch("ai_data_agent.api.deps.build_embedding_client"),
        patch("ai_data_agent.api.deps.build_milvus_store"),
        patch("ai_data_agent.api.deps.build_sql_generation_service"),
    ):
        services = MagicMock()

        # Mock retriever
        services.retriever.search_metadata.return_value = RetrievalContext(
            query="test",
            vector_results=[],
            related_tables={},
            lineage_matches={},
        )

        # Mock context builder
        services.context_builder.build.return_value = TextToSqlContext(
            question="test",
            sources=[],
            tables=[TableContext(name="dws.dws_test", layer="dws", domain="test", description="test table", key_fields=["id"])],
            metrics=[],
            dq_rules=[],
            join_paths=[],
            lineages=[],
        )

        # Mock SQL generator
        guard_result = SqlGuardResult(allowed=True, reasons=[], tables=["dws.dws_test"])
        services.sql_generator.generate.return_value = SqlGenerationResult(
            sql="SELECT * FROM dws.dws_test LIMIT 10",
            prompt="test prompt",
            raw_response="SELECT * FROM dws.dws_test LIMIT 10",
            guard_result=guard_result,
        )

        # Mock Doris executor
        services.doris_executor.execute.return_value = DorisQueryResult(
            columns=["id", "name"],
            rows=[{"id": 1, "name": "test"}],
            row_count=1,
            elapsed_ms=42,
        )
        services.result_analyzer.analyze.return_value = ResultAnalysis(
            answer="住院患者人次为 1。",
            downstream_suggestions=["按科室下钻"],
        )

        mock_build.return_value = services
        yield services


@pytest.fixture()
def app(mock_services, tmp_path):
    db_path = str(tmp_path / "test_memory.db")
    mem = ConversationMemory(db_path=db_path)
    with (
        patch.dict("os.environ", {
            "DORIS_HOST": "localhost", "DORIS_PORT": "9030", "DORIS_USER": "root",
            "DORIS_PASSWORD": "pass", "DORIS_DATABASE": "test",
            "MILVUS_HOST": "localhost", "MILVUS_PORT": "19530", "MILVUS_COLLECTION": "test",
            "LLM_PROVIDER": "openai", "LLM_BASE_URL": "http://localhost", "LLM_MODEL": "gpt-4",
            "LLM_API_KEY": "sk-test", "EMBEDDING_PROVIDER": "openai", "EMBEDDING_BASE_URL": "http://localhost",
            "EMBEDDING_MODEL": "text-embedding-3-small", "EMBEDDING_API_KEY": "sk-test", "EMBEDDING_DIMENSION": "1536",
        }),
        patch("ai_data_agent.api.app.ConversationMemory", return_value=mem),
    ):
        yield create_app(CONFIG_PATH, METADATA_ROOT)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_query_success(client, mock_services):
    response = client.post("/api/v1/query", json={"question": "住院患者人次"})
    assert response.status_code == 200
    data = response.json()
    assert data["question"] == "住院患者人次"
    assert data["sql"] == "SELECT * FROM dws.dws_test LIMIT 10"
    assert data["columns"] == ["id", "name"]
    assert data["row_count"] == 1
    assert data["elapsed_ms"] >= 0
    assert data["request_id"]
    assert data["answer"] == "住院患者人次为 1。"
    assert data["downstream_suggestions"] == ["按科室下钻"]
    assert data["context_summary"]["tables"] == ["dws.dws_test"]
    assert mock_services.audit_logger.write.call_count == 1


def test_query_empty_question_rejected(client):
    response = client.post("/api/v1/query", json={"question": ""})
    assert response.status_code == 422


def test_query_missing_question_rejected(client):
    response = client.post("/api/v1/query", json={})
    assert response.status_code == 422


def test_query_sql_generation_rejected(client, mock_services):
    mock_services.sql_generator.generate.side_effect = SqlGenerationError("SQL Guard rejected: SELECT * is not allowed")
    response = client.post("/api/v1/query", json={"question": "test"})
    assert response.status_code == 422
    assert "rejected" in response.json()["detail"]
    assert mock_services.audit_logger.write.call_count == 1


def test_query_doris_execution_failed(client, mock_services):
    mock_services.doris_executor.execute.side_effect = DorisExecutionError("Connection refused")
    response = client.post("/api/v1/query", json={"question": "test"})
    assert response.status_code == 502
    assert "Doris" in response.json()["detail"]
    assert mock_services.audit_logger.write.call_count == 1


def test_query_retrieval_failed(client, mock_services):
    mock_services.retriever.search_metadata.side_effect = RuntimeError("Milvus unavailable")
    response = client.post("/api/v1/query", json={"question": "test"})
    assert response.status_code == 502
    assert "Retrieval" in response.json()["detail"]
    assert mock_services.audit_logger.write.call_count == 1


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "metadata_tables" in data["checks"]


def test_home_page_serves_query_console(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "医疗数据 Agent" in response.text
    assert "/api/v1/query" in response.text


def test_favicon_endpoint_avoids_browser_404(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 204


def test_query_respects_top_k(client, mock_services):
    client.post("/api/v1/query", json={"question": "test", "top_k": 3})
    mock_services.retriever.search_metadata.assert_called_once_with("test", top_k=3)


def test_query_respects_max_rows(client, mock_services):
    mock_services.doris_executor.execute.return_value = DorisQueryResult(
        columns=["id"],
        rows=[{"id": i} for i in range(200)],
        row_count=200,
        elapsed_ms=10,
    )
    response = client.post("/api/v1/query", json={"question": "test", "max_rows": 5})
    assert response.status_code == 200
    assert response.json()["row_count"] == 5


# ── Agent query with session management ──


def _make_agent_trace(answer: str = "Done.", sql: str | None = None, status: str = "success") -> AgentTrace:
    return AgentTrace(
        request_id="test123",
        question="test",
        steps=[AgentStep(step_number=1, thought=answer, action=None, action_input=None, observation=None, is_final=True, elapsed_ms=10)],
        final_answer=answer,
        final_sql=sql,
        status=status,
        total_elapsed_ms=50,
        total_llm_calls=1,
    )


def test_agent_query_creates_session(client, mock_services):
    mock_services.agent.run.return_value = _make_agent_trace(answer="肿瘤科排名第一")
    response = client.post("/api/v1/agent/query", json={"question": "科室费用排名"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["session_id"]) > 0
    assert data["answer"] == "肿瘤科排名第一"


def test_agent_query_reuses_session(client, mock_services):
    mock_services.agent.run.return_value = _make_agent_trace(answer="A1")
    r1 = client.post("/api/v1/agent/query", json={"question": "Q1", "session_id": "my-session"})
    assert r1.status_code == 200

    # Second call with same session: agent should receive history
    mock_services.agent.run.return_value = _make_agent_trace(answer="A2")
    r2 = client.post("/api/v1/agent/query", json={"question": "Q2", "session_id": "my-session"})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == "my-session"

    # Verify agent.run was called with conversation_history on the second call
    second_call = mock_services.agent.run.call_args_list[-1]
    assert second_call.kwargs.get("conversation_history") is not None or len(second_call.args) >= 3


def test_agent_query_saves_turn_to_memory(client, mock_services):
    mock_services.agent.run.return_value = _make_agent_trace(answer="结果", sql="SELECT 1")
    client.post("/api/v1/agent/query", json={"question": "Q", "session_id": "sess-1"})

    # Check the turn was saved by fetching history
    resp = client.get("/api/v1/sessions/sess-1/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-1"
    assert len(data["turns"]) == 1
    assert data["turns"][0]["question"] == "Q"
    assert data["turns"][0]["answer"] == "结果"
    assert data["turns"][0]["sql"] == "SELECT 1"


def test_agent_query_does_not_save_on_failure(client, mock_services):
    mock_services.agent.run.return_value = _make_agent_trace(answer=None, status="error")
    client.post("/api/v1/agent/query", json={"question": "Q", "session_id": "fail-sess"})

    resp = client.get("/api/v1/sessions/fail-sess/history")
    assert len(resp.json()["turns"]) == 0


def test_session_history_empty(client):
    resp = client.get("/api/v1/sessions/empty-session/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "empty-session"
    assert data["turns"] == []


def test_session_delete(client, mock_services):
    mock_services.agent.run.return_value = _make_agent_trace(answer="ok")
    client.post("/api/v1/agent/query", json={"question": "Q1", "session_id": "del-sess"})
    client.post("/api/v1/agent/query", json={"question": "Q2", "session_id": "del-sess"})

    resp = client.delete("/api/v1/sessions/del-sess")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "del-sess"
    assert data["deleted_turns"] == 2

    # History should now be empty
    history = client.get("/api/v1/sessions/del-sess/history")
    assert history.json()["turns"] == []
