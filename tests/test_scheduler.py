"""Tests for TaskScheduler (task scheduling layer)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_data_agent.agent.loop import AgentStep, AgentTrace
from ai_data_agent.agent.planner import SubTask, TaskPlan
from ai_data_agent.agent.scheduler import TaskScheduler, _enrich_question, SubTaskResult


def _make_trace(answer: str | None, status: str = "success") -> AgentTrace:
    return AgentTrace(
        request_id="req",
        question="test",
        steps=[AgentStep(1, None, None, None, None, True, 10)],
        final_answer=answer,
        final_sql="SELECT 1" if status == "success" else None,
        status=status,
        total_elapsed_ms=50,
        total_llm_calls=1,
    )


@pytest.fixture()
def mock_agent() -> MagicMock:
    return MagicMock()


def test_single_task_success(mock_agent: MagicMock) -> None:
    mock_agent.run.return_value = _make_trace("肺癌患者 120 人")
    plan = TaskPlan(
        original_question="本月肺癌患者多少人",
        sub_tasks=[SubTask("t1", "统计肺癌患者", "本月肺癌患者多少人")],
        execution_order=["t1"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert result.status == "success"
    assert result.sub_results["t1"].status == "success"
    assert "肺癌患者 120 人" in result.final_answer


def test_dependent_task_skipped_when_dep_fails(mock_agent: MagicMock) -> None:
    mock_agent.run.return_value = _make_trace(None, status="error")
    plan = TaskPlan(
        original_question="肺癌患者及其费用",
        sub_tasks=[
            SubTask("t1", "统计患者", "肺癌患者多少人"),
            SubTask("t2", "统计费用", "肺癌费用", depends_on=["t1"]),
        ],
        execution_order=["t1", "t2"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert result.sub_results["t1"].status == "error"
    assert result.sub_results["t2"].status == "skipped"
    assert result.status == "error"


def test_partial_success(mock_agent: MagicMock) -> None:
    mock_agent.run.side_effect = [
        _make_trace("120 人", "success"),
        _make_trace(None, "error"),
    ]
    plan = TaskPlan(
        original_question="肺癌患者及DQ评分",
        sub_tasks=[
            SubTask("t1", "统计患者", "肺癌患者多少人"),
            SubTask("t2", "DQ评分", "DQ评分多少"),
        ],
        execution_order=["t1", "t2"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert result.status == "partial"
    assert result.sub_results["t1"].status == "success"
    assert result.sub_results["t2"].status == "error"


def test_all_tasks_fail_returns_error(mock_agent: MagicMock) -> None:
    mock_agent.run.return_value = _make_trace(None, status="error")
    plan = TaskPlan(
        original_question="复杂查询",
        sub_tasks=[
            SubTask("t1", "子任务1", "Q1"),
            SubTask("t2", "子任务2", "Q2"),
        ],
        execution_order=["t1", "t2"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert result.status == "error"


def test_dep_context_injected_into_next_question(mock_agent: MagicMock) -> None:
    mock_agent.run.side_effect = [
        _make_trace("120 人"),
        _make_trace("费用 5000 元"),
    ]
    plan = TaskPlan(
        original_question="患者数和费用",
        sub_tasks=[
            SubTask("t1", "统计患者", "肺癌患者多少人"),
            SubTask("t2", "统计费用", "费用是多少", depends_on=["t1"]),
        ],
        execution_order=["t1", "t2"],
    )
    TaskScheduler(agent=mock_agent).execute_plan(plan)
    # Second call should receive enriched question containing t1's answer
    second_call_question = mock_agent.run.call_args_list[1][0][0]
    assert "120 人" in second_call_question


def test_elapsed_ms_recorded(mock_agent: MagicMock) -> None:
    mock_agent.run.return_value = _make_trace("ok")
    plan = TaskPlan(
        original_question="Q",
        sub_tasks=[SubTask("t1", "T1", "Q")],
        execution_order=["t1"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert result.total_elapsed_ms >= 0
    assert result.sub_results["t1"].elapsed_ms >= 0


def test_final_answer_contains_all_subtask_descriptions(mock_agent: MagicMock) -> None:
    mock_agent.run.side_effect = [_make_trace("答案A"), _make_trace("答案B")]
    plan = TaskPlan(
        original_question="两步查询",
        sub_tasks=[
            SubTask("t1", "子任务A", "Q_A"),
            SubTask("t2", "子任务B", "Q_B"),
        ],
        execution_order=["t1", "t2"],
    )
    result = TaskScheduler(agent=mock_agent).execute_plan(plan)
    assert "子任务A" in result.final_answer
    assert "子任务B" in result.final_answer


def test_enrich_question_with_dep_results() -> None:
    results = {
        "t1": SubTaskResult("t1", "统计患者", "success", "120 人", None, 10),
    }
    enriched = _enrich_question("费用是多少", ["t1"], results)
    assert "120 人" in enriched
    assert "费用是多少" in enriched


def test_enrich_question_without_deps_unchanged() -> None:
    enriched = _enrich_question("肺癌患者多少人", [], {})
    assert enriched == "肺癌患者多少人"


def test_conversation_history_passed_to_agent(mock_agent: MagicMock) -> None:
    from ai_data_agent.agent.memory import ConversationTurn

    mock_agent.run.return_value = _make_trace("ok")
    history = [ConversationTurn("s1", 1, "上一个问题", "上一个回答", created_at=0.0)]
    plan = TaskPlan(
        original_question="Q",
        sub_tasks=[SubTask("t1", "T1", "Q")],
        execution_order=["t1"],
    )
    TaskScheduler(agent=mock_agent).execute_plan(plan, conversation_history=history)
    call_kwargs = mock_agent.run.call_args
    assert call_kwargs.kwargs.get("conversation_history") == history
