"""Tests for the confidence gate that controls SkillStore writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_data_agent.agent.confidence import ConfidenceScore, ConfidenceScorer
from ai_data_agent.agent.loop import AgentStep, AgentTrace
from ai_data_agent.agent.skill_store import SkillStore
from ai_data_agent.agent.workflow import AgentWorkflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(status: str = "success", final_sql: str | None = "SELECT 1 FROM dwd.t LIMIT 1") -> AgentTrace:
    return AgentTrace(
        request_id="req1",
        question="肺癌患者数量",
        steps=[],
        final_answer="共 42 人",
        final_sql=final_sql,
        status=status,
        total_elapsed_ms=500,
        total_llm_calls=3,
    )


def _make_confidence(overall: float) -> ConfidenceScore:
    return ConfidenceScore(
        overall=overall,
        schema_confidence=overall,
        sql_validity=overall,
        execution_confidence=overall,
        explanation="test",
    )


# ---------------------------------------------------------------------------
# Unit test: workflow only saves to SkillStore when confidence >= threshold
# ---------------------------------------------------------------------------


def _build_workflow(min_confidence: float) -> tuple[AgentWorkflow, MagicMock]:
    """Build an AgentWorkflow with all dependencies mocked."""
    agent_mock = MagicMock()
    planner_mock = MagicMock()
    scheduler_mock = MagicMock()
    memory_mock = MagicMock()
    skill_store_mock = MagicMock(spec=SkillStore)
    scorer_mock = MagicMock(spec=ConfidenceScorer)

    workflow = AgentWorkflow(
        agent=agent_mock,
        planner=planner_mock,
        scheduler=scheduler_mock,
        memory=memory_mock,
        skill_store=skill_store_mock,
        confidence_scorer=scorer_mock,
        min_confidence_to_save=min_confidence,
        skills_dir=None,
    )
    return workflow, skill_store_mock, scorer_mock


def test_skill_store_saved_when_confidence_above_threshold() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="success")
    scorer_mock.score.return_value = _make_confidence(0.85)
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_called_once()


def test_skill_store_not_saved_when_confidence_below_threshold() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="success")
    scorer_mock.score.return_value = _make_confidence(0.5)  # below 0.7
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_not_called()


def test_skill_store_not_saved_when_confidence_exactly_at_threshold() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="success")
    scorer_mock.score.return_value = _make_confidence(0.7)  # exactly at threshold = saved
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_called_once()


def test_skill_store_not_saved_when_no_sql() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="success", final_sql=None)
    scorer_mock.score.return_value = _make_confidence(0.95)
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_not_called()


def test_skill_store_not_saved_on_error_status() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="error")
    scorer_mock.score.return_value = _make_confidence(0.9)
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_not_called()


def test_memory_always_saved_regardless_of_confidence() -> None:
    """Memory is saved for all successful runs, regardless of confidence."""
    workflow, _, scorer_mock = _build_workflow(min_confidence=0.7)

    trace = _make_trace(status="success")
    scorer_mock.score.return_value = _make_confidence(0.3)  # low confidence
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    workflow._memory.save_turn.assert_called_once()


def test_custom_threshold_zero_saves_everything() -> None:
    workflow, skill_store_mock, scorer_mock = _build_workflow(min_confidence=0.0)

    trace = _make_trace(status="success")
    scorer_mock.score.return_value = _make_confidence(0.01)
    workflow._agent.run.return_value = trace
    workflow._memory.get_history.return_value = []
    workflow._skill_store.retrieve_similar.return_value = []

    workflow.run("肺癌患者数量", session_id="s1")

    skill_store_mock.save_skill.assert_called_once()
