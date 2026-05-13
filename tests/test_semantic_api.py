from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_data_agent.agent.memory import ConversationMemory
from ai_data_agent.api.app import create_app
from ai_data_agent.executor.doris import DorisQueryResult

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = str(ROOT / "config" / "application.example.yaml")
METADATA_ROOT = str(ROOT / "metadata")
MODULE_PREFIX = "ai_data_agent.api.app"


@pytest.fixture()
def app(tmp_path):
    services = MagicMock()
    services.query_executor.execute.return_value = DorisQueryResult(
        columns=["dept_name", "antitumor_drug_amount"],
        rows=[{"dept_name": "肿瘤科", "antitumor_drug_amount": 12800}],
        row_count=1,
        elapsed_ms=12,
    )
    with (
        patch(f"{MODULE_PREFIX}.build_query_services", return_value=services),
        patch.dict(
            "os.environ",
            {
                "DORIS_HOST": "localhost",
                "DORIS_PORT": "9030",
                "DORIS_USER": "root",
                "DORIS_PASSWORD": "pass",
                "DORIS_DATABASE": "test",
                "MILVUS_HOST": "localhost",
                "MILVUS_PORT": "19530",
                "MILVUS_COLLECTION": "test",
                "LLM_PROVIDER": "openai",
                "LLM_BASE_URL": "http://localhost",
                "LLM_MODEL": "gpt-4",
                "LLM_API_KEY": "sk-test",
                "EMBEDDING_PROVIDER": "openai",
                "EMBEDDING_BASE_URL": "http://localhost",
                "EMBEDDING_MODEL": "text-embedding-3-small",
                "EMBEDDING_API_KEY": "sk-test",
                "EMBEDDING_DIMENSION": "1536",
                "SEMANTIC_AUDIT_DB_PATH": str(tmp_path / "semantic_audit.db"),
            },
        ),
        patch(
            "ai_data_agent.api.app.ConversationMemory",
            return_value=ConversationMemory(db_path=str(tmp_path / "memory.db")),
        ),
    ):
        yield create_app(CONFIG_PATH, METADATA_ROOT)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_semantic_metrics_endpoint(client):
    response = client.get("/api/v1/semantic/metrics")

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "antitumor_drug_amount"


def test_semantic_dimensions_endpoint(client):
    response = client.get("/api/v1/semantic/dimensions")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert "dept_name" in names


def test_semantic_compile_endpoint(client):
    response = client.post(
        "/api/v1/semantic/compile",
        json={
            "tenant_id": "hospital-a",
            "role": "analyst",
            "metrics": ["antitumor_drug_amount"],
            "dimensions": ["dept_name"],
            "filters": [{"field": "stat_date", "op": "between", "value": ["2026-01-01", "2026-01-31"]}],
            "limit": 100,
        },
    )

    assert response.status_code == 200
    assert "SUM(drug_amount) AS antitumor_drug_amount" in response.json()["sql"]


def test_semantic_query_endpoint_executes_compiled_sql(client, app):
    response = client.post(
        "/api/v1/semantic/query",
        json={
            "tenant_id": "hospital-a",
            "role": "analyst",
            "metrics": ["antitumor_drug_amount"],
            "dimensions": ["dept_name"],
            "filters": [],
            "limit": 100,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 1
    assert payload["rows"][0]["dept_name"] == "肿瘤科"
    app.state.query_services.query_executor.execute.assert_called_once()


def test_semantic_audit_events_include_compile_and_query(client):
    client.post(
        "/api/v1/semantic/compile",
        json={
            "tenant_id": "hospital-a",
            "role": "analyst",
            "metrics": ["antitumor_drug_amount"],
            "dimensions": ["dept_name"],
            "filters": [],
            "limit": 100,
        },
    )
    client.post(
        "/api/v1/semantic/query",
        json={
            "tenant_id": "hospital-a",
            "role": "analyst",
            "metrics": ["antitumor_drug_amount"],
            "dimensions": ["dept_name"],
            "filters": [],
            "limit": 100,
        },
    )

    response = client.get("/api/v1/semantic/audit/events")

    assert response.status_code == 200
    event_types = [item["event_type"] for item in response.json()["items"]]
    assert event_types == ["compile", "query"]


def test_semantic_metric_status_update_persists_and_audits(client):
    response = client.post(
        "/api/v1/semantic/governance/metrics/antitumor_drug_amount/status",
        json={
            "status": "deprecated",
            "actor": "data-steward",
            "reason": "口径升级为 v2",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "antitumor_drug_amount"
    assert response.json()["status"] == "deprecated"

    metrics = client.get("/api/v1/semantic/metrics").json()["items"]
    metric = next(item for item in metrics if item["name"] == "antitumor_drug_amount")
    assert metric["status"] == "deprecated"

    audit = client.get("/api/v1/semantic/audit/events").json()["items"]
    assert audit[-1]["event_type"] == "metric_status_change"
    assert audit[-1]["payload"]["actor"] == "data-steward"


def test_semantic_metric_approval_workflow(client):
    request_response = client.post(
        "/api/v1/semantic/governance/metric-status-requests",
        json={
            "metric_name": "antitumor_drug_amount",
            "requested_status": "deprecated",
            "requester": "analyst-a",
            "reason": "旧口径将被替换",
        },
    )

    assert request_response.status_code == 200
    request_id = request_response.json()["request_id"]
    assert request_response.json()["status"] == "pending"

    list_response = client.get("/api/v1/semantic/governance/metric-status-requests")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["request_id"] == request_id

    approve_response = client.post(
        f"/api/v1/semantic/governance/metric-status-requests/{request_id}/approve",
        json={"reviewer": "chief-data-office", "comment": "同意"},
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    metric = next(
        item
        for item in client.get("/api/v1/semantic/metrics").json()["items"]
        if item["name"] == "antitumor_drug_amount"
    )
    assert metric["status"] == "deprecated"

    audit_events = client.get("/api/v1/semantic/audit/events").json()["items"]
    assert [event["event_type"] for event in audit_events[-2:]] == [
        "metric_status_request",
        "metric_status_approved",
    ]
