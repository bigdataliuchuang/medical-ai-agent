"""Tests for Phase 5 advanced features."""

from __future__ import annotations

from unittest.mock import MagicMock

from ai_data_agent.agent.confidence import ConfidenceScorer
from ai_data_agent.agent.loop import AgentStep, AgentTrace
from ai_data_agent.agent.planner import TaskPlanner, SubTask
from ai_data_agent.executor.doris import DorisQueryResult, DorisExecutionError
from ai_data_agent.executor.sandbox import SandboxedExecutor
from ai_data_agent.text2sql.llm import LlmResponse
from ai_data_agent.text2sql.sql_guard import SqlGuard, SqlGuardResult
from ai_data_agent.text2sql.few_shot import FewShotSelector, load_few_shot_examples
from ai_data_agent.text2sql.prompt_builder import FewShotExample


# --- Few-Shot Tests ---

def test_few_shot_selector_table_overlap():
    examples = [
        FewShotExample(question="q1", sql="SELECT ...", domain="drug", tables=["dws.dws_drug_1d"]),
        FewShotExample(question="q2", sql="SELECT ...", domain="tumor", tables=["dws.dws_tumor_1d"]),
        FewShotExample(question="q3", sql="SELECT ...", domain="dq", tables=["dq.dq_check"]),
    ]
    selector = FewShotSelector(examples)
    selected = selector.select("drug question", context_tables=["dws.dws_drug_1d", "dws.dws_tumor_1d"], top_k=2)
    assert len(selected) == 2
    # First should have table overlap
    assert any(t in selected[0].tables for t in ["dws.dws_drug_1d", "dws.dws_tumor_1d"])


def test_few_shot_selector_empty():
    selector = FewShotSelector([])
    assert selector.select("any question", []) == []


def test_load_few_shot_examples_nonexistent(tmp_path):
    examples = load_few_shot_examples(tmp_path / "nonexistent.jsonl")
    assert examples == []


# --- Confidence Tests ---

def test_confidence_scorer_success():
    scorer = ConfidenceScorer()
    trace = AgentTrace(
        request_id="r1", question="q", steps=[],
        final_answer="ok", final_sql="SELECT ...", status="success",
        total_elapsed_ms=100, total_llm_calls=1,
    )
    score = scorer.score(trace, retrieval_score=0.9)
    assert score.overall > 0.5
    assert score.schema_confidence == 0.9


def test_confidence_scorer_max_steps():
    scorer = ConfidenceScorer()
    trace = AgentTrace(
        request_id="r1", question="q", steps=[],
        final_answer=None, final_sql=None, status="max_steps",
        total_elapsed_ms=100, total_llm_calls=8,
    )
    score = scorer.score(trace)
    # max_steps status reduces agent_confidence to 0.2, pulling overall down
    assert score.overall < 0.7
    assert "Agent" in score.explanation or "未正常完成" in score.explanation


def test_confidence_scorer_with_execution():
    scorer = ConfidenceScorer()
    trace = AgentTrace(
        request_id="r1", question="q", steps=[],
        final_answer="ok", final_sql="SELECT ...", status="success",
        total_elapsed_ms=100, total_llm_calls=1,
    )
    result = DorisQueryResult(columns=["a"], rows=[{"a": 1}], row_count=1, elapsed_ms=10)
    score = scorer.score(trace, execution_result=result)
    assert score.execution_confidence == 0.9


# --- Planner Tests ---

def test_task_planner_single_task():
    llm = MagicMock()
    llm.complete.return_value = '[{"description": "直接查询", "question": "查询药品使用量", "depends_on": []}]'
    planner = TaskPlanner(llm)
    plan = planner.plan("查询药品使用量")
    assert len(plan.sub_tasks) == 1
    assert plan.execution_order == ["task_1"]


def test_task_planner_multi_task():
    llm = MagicMock()
    llm.complete.return_value = '''[
        {"description": "查询各科室药品费用", "question": "查询各科室的药品费用", "depends_on": []},
        {"description": "找出异常科室", "question": "找出药品费用异常增长的科室", "depends_on": ["查询各科室药品费用"]}
    ]'''
    planner = TaskPlanner(llm)
    plan = planner.plan("分析各科室药品费用异常情况")
    assert len(plan.sub_tasks) == 2
    assert plan.execution_order == ["task_1", "task_2"]


def test_task_planner_json_fallback():
    llm = MagicMock()
    llm.complete.return_value = "not valid json"
    planner = TaskPlanner(llm)
    plan = planner.plan("simple question")
    assert len(plan.sub_tasks) == 1


# --- Sandbox Tests ---

def test_sandbox_adds_limit():
    executor = MagicMock()
    executor.execute.return_value = DorisQueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0)
    sandbox = SandboxedExecutor(executor, max_rows=500)
    sandbox.execute("SELECT col FROM dws.t")
    call_args = executor.execute.call_args[0][0]
    assert "LIMIT 500" in call_args


def test_sandbox_preserves_existing_limit():
    executor = MagicMock()
    executor.execute.return_value = DorisQueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0)
    sandbox = SandboxedExecutor(executor, max_rows=500)
    sandbox.execute("SELECT col FROM dws.t LIMIT 10")
    call_args = executor.execute.call_args[0][0]
    assert "LIMIT 10" in call_args


def test_sandbox_guard_rejects():
    executor = MagicMock()
    guard = MagicMock()
    guard.validate.return_value = SqlGuardResult(allowed=False, reasons=["SELECT * not allowed"])
    sandbox = SandboxedExecutor(executor, guard=guard)
    try:
        sandbox.execute("SELECT * FROM dws.t")
        assert False, "Should have raised"
    except DorisExecutionError as e:
        assert "validation failed" in str(e).lower()
