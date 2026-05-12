from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dev import router
from agent.warehouse_dev import build_metric_plan, save_metric_asset


def test_save_metric_asset_writes_yaml_and_markdown(tmp_path: Path) -> None:
    plan = build_metric_plan("我要做抗肿瘤药物使用强度指标")

    result = save_metric_asset(plan, tmp_path)

    yaml_path = tmp_path / "antitumor_drug_usage_intensity.yaml"
    md_path = tmp_path / "antitumor_drug_usage_intensity.md"
    assert result["metric_code"] == "antitumor_drug_usage_intensity"
    assert result["yaml_path"] == str(yaml_path)
    assert result["markdown_path"] == str(md_path)
    assert yaml_path.exists()
    assert md_path.exists()

    saved = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert saved["metric_code"] == "antitumor_drug_usage_intensity"
    assert saved["source_tables"] == ["dws.dws_tumor_drug_usage_1d"]
    assert saved["drilldown_policy"]["default_layer"] == "ADS/DWS"
    assert "抗肿瘤药物使用强度" in md_path.read_text(encoding="utf-8")


def test_metric_asset_endpoint_saves_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METRIC_ASSET_OUTPUT_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    plan = build_metric_plan("我要分析待审核重复患者队列")

    response = client.post("/api/dev/metric-assets", json={"plan": plan})

    assert response.status_code == 200
    data = response.json()
    assert data["metric_code"] == "mpi_pending_review_cnt"
    assert (tmp_path / "mpi_pending_review_cnt.yaml").exists()
    assert (tmp_path / "mpi_pending_review_cnt.md").exists()
