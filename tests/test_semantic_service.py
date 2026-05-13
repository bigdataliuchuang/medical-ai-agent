from pathlib import Path

import pytest


def test_semantic_catalog_loads_metrics_dimensions_and_datasets():
    from ai_data_agent.semantic_service.catalog import SemanticCatalog

    catalog = SemanticCatalog.load(Path("metadata/semantic"))

    metric = catalog.get_metric("antitumor_drug_amount")
    dimension = catalog.get_dimension("dept_name")
    dataset = catalog.get_dataset("tumor_drug_usage")

    assert metric.display_name == "抗肿瘤药物使用金额"
    assert dimension.display_name == "科室名称"
    assert dataset.table == "dws.dws_tumor_drug_usage_1d"


def test_policy_rejects_metric_for_unauthorized_role():
    from ai_data_agent.semantic_service.catalog import SemanticCatalog
    from ai_data_agent.semantic_service.dsl import SemanticQueryRequest
    from ai_data_agent.semantic_service.policy import PolicyEngine, PolicyViolation

    catalog = SemanticCatalog.load(Path("metadata/semantic"))
    policy = PolicyEngine(catalog)
    request = SemanticQueryRequest(
        tenant_id="hospital-a",
        role="viewer",
        metrics=["antitumor_drug_amount"],
        dimensions=["dept_name"],
        filters=[],
        limit=100,
    )

    with pytest.raises(PolicyViolation, match="not allowed to access metric"):
        policy.authorize(request)


def test_policy_rejects_sensitive_dimension_without_permission():
    from ai_data_agent.semantic_service.catalog import SemanticCatalog
    from ai_data_agent.semantic_service.dsl import SemanticQueryRequest
    from ai_data_agent.semantic_service.policy import PolicyEngine, PolicyViolation

    catalog = SemanticCatalog.load(Path("metadata/semantic"))
    policy = PolicyEngine(catalog)
    request = SemanticQueryRequest(
        tenant_id="hospital-a",
        role="analyst",
        metrics=["patient_count"],
        dimensions=["mpi_id"],
        filters=[],
        limit=100,
    )

    with pytest.raises(PolicyViolation, match="sensitive dimension"):
        policy.authorize(request)


def test_compiler_generates_grouped_sql_with_metric_and_request_filters():
    from ai_data_agent.semantic_service.catalog import SemanticCatalog
    from ai_data_agent.semantic_service.compiler import SemanticSqlCompiler
    from ai_data_agent.semantic_service.dsl import SemanticFilter, SemanticQueryRequest

    catalog = SemanticCatalog.load(Path("metadata/semantic"))
    compiler = SemanticSqlCompiler(catalog)
    request = SemanticQueryRequest(
        tenant_id="hospital-a",
        role="analyst",
        metrics=["antitumor_drug_amount"],
        dimensions=["dept_name", "drug_name"],
        filters=[
            SemanticFilter(
                field="stat_date",
                op="between",
                value=["2026-01-01", "2026-01-31"],
            )
        ],
        limit=100,
    )

    compiled = compiler.compile(request)

    assert compiled.sql == (
        "SELECT\n"
        "  dept_name,\n"
        "  drug_name,\n"
        "  SUM(drug_amount) AS antitumor_drug_amount\n"
        "FROM dws.dws_tumor_drug_usage_1d\n"
        "WHERE drug_category = 'ANTITUMOR'\n"
        "  AND stat_date BETWEEN '2026-01-01' AND '2026-01-31'\n"
        "GROUP BY dept_name, drug_name\n"
        "LIMIT 100"
    )
    assert compiled.dataset == "tumor_drug_usage"
    assert compiled.metrics == ["antitumor_drug_amount"]
    assert compiled.dimensions == ["dept_name", "drug_name"]


def test_sqlite_audit_store_persists_events(tmp_path):
    from ai_data_agent.semantic_service.audit import SemanticAuditEvent, SQLiteSemanticAuditStore

    db_path = tmp_path / "semantic_audit.db"
    store = SQLiteSemanticAuditStore(db_path)
    store.append(
        SemanticAuditEvent.create(
            event_type="compile",
            tenant_id="hospital-a",
            role="analyst",
            status="success",
            message="compiled",
            payload={"sql": "SELECT 1"},
        )
    )

    reloaded = SQLiteSemanticAuditStore(db_path)
    events = reloaded.list_events()

    assert len(events) == 1
    assert events[0]["event_type"] == "compile"
    assert events[0]["payload"] == {"sql": "SELECT 1"}
