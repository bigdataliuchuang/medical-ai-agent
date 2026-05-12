"""Tests for AgentWorkflow (top-level five-layer orchestrator)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_data_agent.agent.loop import AgentStep, AgentTrace
from ai_data_agent.agent.memory import ConversationMemory
from ai_data_agent.agent.planner import SubTask, TaskPlan, TaskPlanner
from ai_data_agent.agent.scheduler import SchedulerResult, TaskScheduler
from ai_data_agent.agent.skill_store import SkillStore
from ai_data_agent.agent.workflow import AgentWorkflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    answer: str | None,
    status: str = "success",
    sql: str | None = "SELECT 1",
) -> AgentTrace:
    return AgentTrace(
        request_id="r1",
        question="test",
        steps=[AgentStep(1, None, None, None, None, True, 10)],
        final_answer=answer,
        final_sql=sql if status == "success" else None,
        status=status,
        total_elapsed_ms=50,
        total_llm_calls=1,
    )


def _make_scheduler_result(answer: str, status: str = "success") -> SchedulerResult:
    plan = TaskPlan("Q", [SubTask("t1", "T1", "Q")], ["t1"])
    return SchedulerResult(
        plan=plan,
        sub_results={},
        final_answer=answer,
        status=status,
        total_elapsed_ms=100,
    )


@pytest.fixture()
def wf(tmp_path: Path):
    agent = MagicMock()
    planner = MagicMock(spec=TaskPlanner)
    scheduler = MagicMock(spec=TaskScheduler)
    memory = ConversationMemory(db_path=str(tmp_path / "mem.db"))
    skill_store = SkillStore(db_path=str(tmp_path / "skills.db"))
    workflow = AgentWorkflow(agent, planner, scheduler, memory, skill_store)
    return workflow, agent, planner, scheduler, memory, skill_store


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


def test_simple_question_uses_direct_path(wf) -> None:
    workflow, agent, planner, scheduler, *_ = wf
    agent.run.return_value = _make_trace("120 人")

    result = workflow.run("本月肺癌患者多少人", session_id="s1")

    assert result.status == "success"
    assert result.trace is not None
    assert result.scheduler_result is None
    planner.plan.assert_not_called()
    scheduler.execute_plan.assert_not_called()


def test_complex_question_uses_planner(wf) -> None:
    workflow, agent, planner, scheduler, *_ = wf
    planner.plan.return_value = TaskPlan("Q", [SubTask("t1", "T1", "Q")], ["t1"])
    scheduler.execute_plan.return_value = _make_scheduler_result("综合答案")

    result = workflow.run("同时统计肺癌患者数量并且查看DQ评分趋势", session_id="s2")

    assert result.scheduler_result is not None
    assert result.trace is None
    assert result.answer == "综合答案"
    planner.plan.assert_called_once()


# ---------------------------------------------------------------------------
# Memory persistence tests
# ---------------------------------------------------------------------------


def test_successful_run_saves_to_memory(wf) -> None:
    workflow, agent, _, __, memory, ___ = wf
    agent.run.return_value = _make_trace("答案")

    workflow.run("查询患者数据", session_id="s3")

    history = memory.get_history("s3")
    assert len(history) == 1
    assert history[0].question == "查询患者数据"
    assert history[0].answer == "答案"


def test_failed_run_does_not_save_to_memory(wf) -> None:
    workflow, agent, _, __, memory, ___ = wf
    agent.run.return_value = _make_trace(None, status="error", sql=None)

    workflow.run("失败的查询", session_id="s4")

    history = memory.get_history("s4")
    assert len(history) == 0


def test_partial_scheduler_result_saves_to_memory(wf) -> None:
    workflow, agent, planner, scheduler, memory, _ = wf
    planner.plan.return_value = TaskPlan("Q", [SubTask("t1", "T1", "Q")], ["t1"])
    scheduler.execute_plan.return_value = _make_scheduler_result("部分答案", status="partial")

    workflow.run("同时查询患者数量并且看费用趋势", session_id="s5")

    history = memory.get_history("s5")
    assert len(history) == 1


# ---------------------------------------------------------------------------
# Skill store persistence tests
# ---------------------------------------------------------------------------


def test_successful_run_saves_skill(wf) -> None:
    workflow, agent, _, __, ___, skill_store = wf
    agent.run.return_value = _make_trace("120 人", sql="SELECT cnt FROM ads.t")

    workflow.run("查询患者数", session_id="s6")

    assert skill_store.get_stats()["total_skills"] == 1


def test_failed_run_does_not_save_skill(wf) -> None:
    workflow, agent, _, __, ___, skill_store = wf
    agent.run.return_value = _make_trace(None, status="error", sql=None)

    workflow.run("失败查询", session_id="s7")

    assert skill_store.get_stats()["total_skills"] == 0


def test_no_sql_does_not_save_skill(wf) -> None:
    workflow, agent, _, __, ___, skill_store = wf
    # Successful trace but sql=None (e.g. concept explanation)
    agent.run.return_value = _make_trace("概念解释", sql=None)

    workflow.run("什么是MPI", session_id="s8")

    assert skill_store.get_stats()["total_skills"] == 0


# ---------------------------------------------------------------------------
# Skill hit reporting
# ---------------------------------------------------------------------------


def test_skill_hit_reported_when_similar_exists(wf) -> None:
    workflow, agent, _, __, ___, skill_store = wf
    skill_store.save_skill("查询患者数量", "SELECT cnt FROM ads.t", answer_summary="100 人")
    agent.run.return_value = _make_trace("结果")

    result = workflow.run("查询患者数量统计", session_id="s9")

    # skill_hit is set when a similar pattern was found before execution
    assert result.skill_hit is not None


def test_no_skill_hit_when_store_empty(wf) -> None:
    workflow, agent, _, __, ___, ___ = wf
    agent.run.return_value = _make_trace("结果")

    result = workflow.run("完全陌生的问题", session_id="s10")

    assert result.skill_hit is None


# ---------------------------------------------------------------------------
# Request ID and session ID
# ---------------------------------------------------------------------------


def test_custom_request_id_propagated(wf) -> None:
    workflow, agent, *_ = wf
    agent.run.return_value = _make_trace("答案")

    result = workflow.run("查询", session_id="s11", request_id="my_req")

    assert result.request_id == "my_req"


def test_auto_session_id_generated_when_empty(wf) -> None:
    workflow, agent, *_ = wf
    agent.run.return_value = _make_trace("答案")

    result = workflow.run("查询")

    assert len(result.session_id) > 0


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def test_confidence_populated_on_direct_success(wf) -> None:
    workflow, agent, *_ = wf
    agent.run.return_value = _make_trace("答案")

    result = workflow.run("查询", session_id="s12")

    assert result.confidence is not None
    assert 0.0 <= result.confidence.overall <= 1.0


def test_confidence_none_for_planned_execution(wf) -> None:
    workflow, agent, planner, scheduler, *_ = wf
    planner.plan.return_value = TaskPlan("Q", [SubTask("t1", "T1", "Q")], ["t1"])
    scheduler.execute_plan.return_value = _make_scheduler_result("综合答案")

    result = workflow.run("同时查询患者并且分析费用对比", session_id="s13")

    assert result.confidence is None


# ---------------------------------------------------------------------------
# Elapsed time
# ---------------------------------------------------------------------------


def test_elapsed_ms_is_non_negative(wf) -> None:
    workflow, agent, *_ = wf
    agent.run.return_value = _make_trace("答案")

    result = workflow.run("查询", session_id="s14")

    assert result.elapsed_ms >= 0
