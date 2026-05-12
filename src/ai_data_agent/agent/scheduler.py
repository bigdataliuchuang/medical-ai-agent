"""Task scheduling layer: execute a TaskPlan in dependency order."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ai_data_agent.agent.loop import AgentTrace, ReActAgent
from ai_data_agent.agent.memory import ConversationTurn
from ai_data_agent.agent.planner import TaskPlan


@dataclass
class SubTaskResult:
    """Outcome of a single sub-task execution."""

    task_id: str
    description: str
    status: str  # "success" | "error" | "skipped"
    answer: str | None
    sql: str | None
    elapsed_ms: int
    trace: AgentTrace | None = None


@dataclass
class SchedulerResult:
    """Aggregated result of executing a full TaskPlan."""

    plan: TaskPlan
    sub_results: dict[str, SubTaskResult]
    final_answer: str
    status: str  # "success" | "partial" | "error"
    total_elapsed_ms: int


class TaskScheduler:
    """Execute a TaskPlan in topological dependency order using a ReActAgent.

    For each sub-task the scheduler:
    1. Skips it if any dependency failed.
    2. Enriches the question with the text results of completed dependencies.
    3. Delegates execution to the ReActAgent.
    4. Collects per-sub-task traces and synthesises a final answer.
    """

    def __init__(self, agent: ReActAgent) -> None:
        self._agent = agent

    def execute_plan(
        self,
        plan: TaskPlan,
        conversation_history: list[ConversationTurn] | None = None,
    ) -> SchedulerResult:
        started = time.monotonic()
        sub_results: dict[str, SubTaskResult] = {}
        task_map = {t.id: t for t in plan.sub_tasks}

        for task_id in plan.execution_order:
            task = task_map.get(task_id)
            if task is None:
                continue

            # Skip if any dependency did not succeed
            failed_deps = [
                dep
                for dep in task.depends_on
                if sub_results.get(dep, SubTaskResult(dep, "", "error", None, None, 0)).status
                != "success"
            ]
            if failed_deps:
                sub_results[task_id] = SubTaskResult(
                    task_id=task_id,
                    description=task.description,
                    status="skipped",
                    answer=f"Skipped: upstream tasks {failed_deps} did not succeed",
                    sql=None,
                    elapsed_ms=0,
                )
                continue

            enriched = _enrich_question(task.question, task.depends_on, sub_results)

            task_started = time.monotonic()
            trace = self._agent.run(enriched, conversation_history=conversation_history)
            task_elapsed = int((time.monotonic() - task_started) * 1000)

            if trace.status == "success" and trace.final_answer:
                sub_results[task_id] = SubTaskResult(
                    task_id=task_id,
                    description=task.description,
                    status="success",
                    answer=trace.final_answer,
                    sql=trace.final_sql,
                    elapsed_ms=task_elapsed,
                    trace=trace,
                )
            else:
                sub_results[task_id] = SubTaskResult(
                    task_id=task_id,
                    description=task.description,
                    status="error",
                    answer=None,
                    sql=trace.final_sql,
                    elapsed_ms=task_elapsed,
                    trace=trace,
                )

        final_answer = _synthesize_answer(plan.original_question, sub_results)
        success_count = sum(1 for r in sub_results.values() if r.status == "success")
        total = len(sub_results)

        if success_count == total and total > 0:
            status = "success"
        elif success_count > 0:
            status = "partial"
        else:
            status = "error"

        return SchedulerResult(
            plan=plan,
            sub_results=sub_results,
            final_answer=final_answer,
            status=status,
            total_elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def _enrich_question(
    question: str,
    dep_ids: list[str],
    results: dict[str, SubTaskResult],
) -> str:
    if not dep_ids:
        return question
    context_parts = [
        f"[{results[dep].description}]: {results[dep].answer}"
        for dep in dep_ids
        if dep in results and results[dep].answer
    ]
    if not context_parts:
        return question
    context = "\n".join(context_parts)
    return f"上下文信息：\n{context}\n\n当前问题：{question}"


def _synthesize_answer(
    original_question: str,
    results: dict[str, SubTaskResult],
) -> str:
    if not results:
        return "所有子任务均未能完成，请检查问题或数据配置。"
    parts = []
    for res in results.values():
        if res.status == "success" and res.answer:
            parts.append(f"**{res.description}**：{res.answer}")
        elif res.status == "error":
            parts.append(f"**{res.description}**：（查询失败）")
        elif res.status == "skipped":
            parts.append(f"**{res.description}**：（已跳过，依赖任务失败）")
    return "\n\n".join(parts) if parts else "所有子任务均未能完成。"
