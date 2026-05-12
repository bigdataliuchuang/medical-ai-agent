import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent.warehouse_dev import build_metric_plan, save_metric_asset


router = APIRouter()


class MetricPlanRequest(BaseModel):
    requirement: str = Field(..., min_length=2, max_length=1000)
    domain: str | None = Field(default=None, max_length=100)


class MetricAssetRequest(BaseModel):
    plan: dict[str, Any]


@router.post("/api/dev/metric-plan")
async def metric_plan(req: MetricPlanRequest):
    return build_metric_plan(req.requirement, req.domain)


@router.post("/api/dev/metric-assets")
async def metric_assets(req: MetricAssetRequest):
    output_dir = os.getenv("METRIC_ASSET_OUTPUT_DIR")
    return save_metric_asset(req.plan, output_dir)
