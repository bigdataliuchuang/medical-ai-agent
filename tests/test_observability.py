"""Tests for observability components."""

from __future__ import annotations

import json

from ai_data_agent.agent.audit import AgentStepRecord, AgentTraceRecord
from ai_data_agent.observability.cost import CostEstimate, CostTracker
from ai_data_agent.observability.logger import LogContext, StructuredLogger


def test_structured_logger_outputs_json(capsys):
    logger = StructuredLogger("test.agent")
    logger.info("tool_call", tool="execute_sql", elapsed_ms=42)
    captured = capsys.readouterr()
    entry = json.loads(captured.err)
    assert entry["level"] == "INFO"
    assert entry["event"] == "tool_call"
    assert entry["tool"] == "execute_sql"
    assert entry["elapsed_ms"] == 42
    assert entry["logger"] == "test.agent"
    assert "timestamp" in entry


def test_bound_logger_includes_context(capsys):
    logger = StructuredLogger("test.agent")
    ctx = LogContext(request_id="req_123", agent_step=2, tool_name="validate_sql")
    bound = logger.with_context(ctx)
    bound.info("validation_done")
    captured = capsys.readouterr()
    entry = json.loads(captured.err)
    assert entry["request_id"] == "req_123"
    assert entry["agent_step"] == 2
    assert entry["tool_name"] == "validate_sql"


def test_cost_tracker_estimate():
    tracker = CostTracker()
    estimate = tracker.estimate("gpt-4o", {"prompt_tokens": 1000, "completion_tokens": 500})
    assert estimate.prompt_tokens == 1000
    assert estimate.completion_tokens == 500
    assert estimate.total_tokens == 1500
    assert estimate.estimated_cost_usd > 0


def test_cost_tracker_accumulate():
    tracker = CostTracker()
    usages = [
        {"prompt_tokens": 500, "completion_tokens": 200},
        {"prompt_tokens": 800, "completion_tokens": 300},
    ]
    total = tracker.accumulate(usages, model="gpt-4o")
    assert total.prompt_tokens == 1300
    assert total.completion_tokens == 500
    assert total.total_tokens == 1800


def test_cost_tracker_unknown_model():
    tracker = CostTracker()
    estimate = tracker.estimate("unknown-model", {"prompt_tokens": 100, "completion_tokens": 50})
    # Falls back to default pricing
    assert estimate.estimated_cost_usd > 0


def test_agent_trace_record_with_timestamp():
    record = AgentTraceRecord(
        request_id="req_1",
        question="test",
        steps=[],
        final_sql=None,
        final_answer=None,
        status="success",
        total_elapsed_ms=100,
        total_llm_calls=1,
    )
    assert record.created_at == ""
    stamped = record.with_timestamp()
    assert stamped.created_at != ""
    assert stamped.request_id == "req_1"


def test_agent_step_record():
    step = AgentStepRecord(
        step_number=1,
        thought="I need to search metadata",
        tool_name="search_metadata",
        tool_input={"question": "test"},
        tool_output='{"tables": ["dws.t"]}',
        tool_success=True,
        elapsed_ms=50,
    )
    assert step.step_number == 1
    assert step.tool_name == "search_metadata"
    assert step.tool_success is True
