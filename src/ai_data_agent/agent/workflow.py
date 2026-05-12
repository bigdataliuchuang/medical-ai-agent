"""Workflow orchestrator: integrates all five agent layers into a single entry point."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from ai_data_agent.agent.confidence import ConfidenceScore, ConfidenceScorer
from ai_data_agent.agent.loop import AgentTrace, ReActAgent
from ai_data_agent.agent.memory import ConversationMemory, ConversationTurn
from ai_data_agent.agent.planner import TaskPlanner
from ai_data_agent.agent.scheduler import SchedulerResult, TaskScheduler
from ai_data_agent.agent.skill_store import SkillRecord, SkillStore

# Questions containing ≥ this many complexity keywords are routed through the planner.
_COMPLEXITY_THRESHOLD = 2
_COMPLEXITY_KEYWORDS = [
    "同时", "并且", "以及", "另外", "分别", "对比", "比较",
    "趋势", "变化", "多个", "各个", "每个",
]


@dataclass(frozen=True)
class WorkflowResult:
    """Complete result returned by the workflow orchestrator."""

    question: str
    session_id: str
    answer: str
    sql: str | None
    status: str  # "success" | "partial" | "error"
    skill_hit: SkillRecord | None  # best matching skill retrieved before execution
    trace: AgentTrace | None  # populated for single-step execution
    scheduler_result: SchedulerResult | None  # populated for multi-step execution
    confidence: ConfidenceScore | None
    elapsed_ms: int
    request_id: str


class AgentWorkflow:
    """Top-level orchestrator that wires together all five agent layers:

    1. LLM reasoning  — ReActAgent (Thought → Action → Observation loop)
    2. Tool calling   — ToolRegistry inside ReActAgent
    3. Memory         — ConversationMemory (SQLite, per-session turn history)
    4. Skill store    — SkillStore (accumulate successful patterns, few-shot reuse)
    5. Task scheduler — TaskPlanner + TaskScheduler (decompose & execute complex queries)
    """

    def __init__(
        self,
        agent: ReActAgent,
        planner: TaskPlanner,
        scheduler: TaskScheduler,
        memory: ConversationMemory,
        skill_store: SkillStore,
        confidence_scorer: ConfidenceScorer | None = None,
        complexity_threshold: int = _COMPLEXITY_THRESHOLD,
    ) -> None:
        self._agent = agent
        self._planner = planner
        self._scheduler = scheduler
        self._memory = memory
        self._skill_store = skill_store
        self._scorer = confidence_scorer or ConfidenceScorer()
        self._complexity_threshold = complexity_threshold

    def run(
        self,
        question: str,
        session_id: str = "",
        request_id: str | None = None,
    ) -> WorkflowResult:
        """Execute a question through the full workflow.

        Steps:
        1. Fetch conversation history from memory layer.
        2. Probe skill store for a similar past pattern.
        3. If question looks complex, decompose via planner → execute via scheduler.
        4. Otherwise run the ReAct agent directly.
        5. Persist successful results back to memory and skill store.
        """
        request_id = request_id or uuid.uuid4().hex[:16]
        session_id = session_id or uuid.uuid4().hex[:16]
        started = time.monotonic()

        # Layer 3 – Memory: retrieve conversation history
        history = self._memory.get_history(session_id)

        # Layer 4 – Skill store: probe for a reusable pattern
        skill_hits = self._skill_store.retrieve_similar(question, top_k=1)
        skill_hit = skill_hits[0] if skill_hits else None

        # Layer 5 – Task scheduling: complex questions are decomposed first
        if self._is_complex(question):
            return self._run_planned(question, session_id, request_id, history, skill_hit, started)

        # Layers 1+2 – LLM reasoning + tool calling: direct ReAct execution
        return self._run_direct(question, session_id, request_id, history, skill_hit, started)

    # ------------------------------------------------------------------
    # Internal execution paths
    # ------------------------------------------------------------------

    def _is_complex(self, question: str) -> bool:
        count = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in question)
        return count >= self._complexity_threshold

    def _run_direct(
        self,
        question: str,
        session_id: str,
        request_id: str,
        history: list[ConversationTurn],
        skill_hit: SkillRecord | None,
        started: float,
    ) -> WorkflowResult:
        trace = self._agent.run(
            question,
            request_id=request_id,
            conversation_history=history,
        )

        confidence = self._scorer.score(trace)
        elapsed = int((time.monotonic() - started) * 1000)
        answer = trace.final_answer or "Agent 未能生成答案，请重新提问。"
        status = trace.status if trace.status in ("success", "error") else "error"

        if trace.status == "success":
            tables = _extract_tables(trace)
            self._memory.save_turn(
                session_id, question, answer, sql=trace.final_sql, tables_used=tables
            )
            if trace.final_sql:
                self._skill_store.save_skill(
                    question=question,
                    sql=trace.final_sql,
                    tables_used=tables,
                    answer_summary=answer[:200],
                    latency_ms=float(elapsed),
                )

        return WorkflowResult(
            question=question,
            session_id=session_id,
            answer=answer,
            sql=trace.final_sql,
            status=status,
            skill_hit=skill_hit,
            trace=trace,
            scheduler_result=None,
            confidence=confidence,
            elapsed_ms=elapsed,
            request_id=request_id,
        )

    def _run_planned(
        self,
        question: str,
        session_id: str,
        request_id: str,
        history: list[ConversationTurn],
        skill_hit: SkillRecord | None,
        started: float,
    ) -> WorkflowResult:
        plan = self._planner.plan(question)
        sched_result = self._scheduler.execute_plan(plan, conversation_history=history)
        elapsed = int((time.monotonic() - started) * 1000)
        answer = sched_result.final_answer
        status = sched_result.status

        if status in ("success", "partial"):
            self._memory.save_turn(session_id, question, answer)

        return WorkflowResult(
            question=question,
            session_id=session_id,
            answer=answer,
            sql=None,
            status=status,
            skill_hit=skill_hit,
            trace=None,
            scheduler_result=sched_result,
            confidence=None,
            elapsed_ms=elapsed,
            request_id=request_id,
        )


def _extract_tables(trace: AgentTrace) -> list[str]:
    """Pull table names out of search_metadata observations in the trace."""
    tables: list[str] = []
    for step in trace.steps:
        if step.action == "search_metadata" and step.observation:
            try:
                data = json.loads(step.observation)
                tables.extend(data.get("tables", []))
            except (json.JSONDecodeError, TypeError):
                pass
    seen: set[str] = set()
    return [t for t in tables if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
