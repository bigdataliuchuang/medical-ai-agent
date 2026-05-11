"""Task planning for complex multi-part queries."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from ai_data_agent.text2sql.llm import LlmClient


@dataclass(frozen=True)
class SubTask:
    """A decomposed sub-task of a complex query."""

    id: str
    description: str
    question: str
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskPlan:
    """A plan decomposing a complex question into sub-tasks."""

    original_question: str
    sub_tasks: list[SubTask]
    execution_order: list[str]  # topological order


_PLANNING_PROMPT = """你是医疗数据治理平台的任务规划器。
用户提出了一个复杂的数据分析问题，需要拆分为多个子任务。

请将以下问题拆分为可独立执行的子任务，每个子任务对应一个 SQL 查询。
输出 JSON 数组，每个元素包含：
- description: 子任务描述
- question: 对应的自然语言问题
- depends_on: 依赖的其他子任务 description 列表（可为空）

问题：{question}

只输出 JSON 数组，不要输出其他内容。"""


class TaskPlanner:
    """Decompose complex questions into executable sub-tasks."""

    def __init__(self, llm: LlmClient):
        self._llm = llm

    def plan(self, question: str) -> TaskPlan:
        prompt = _PLANNING_PROMPT.format(question=question)
        raw = self._llm.complete(prompt)

        # Extract JSON from response
        try:
            # Try to find JSON array in the response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                tasks_raw = json.loads(raw[start:end])
            else:
                tasks_raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Fallback: single task
            return TaskPlan(
                original_question=question,
                sub_tasks=[SubTask(id="task_1", description="直接回答", question=question)],
                execution_order=["task_1"],
            )

        sub_tasks: list[SubTask] = []
        desc_to_id: dict[str, str] = {}
        for i, t in enumerate(tasks_raw, 1):
            task_id = f"task_{i}"
            desc = t.get("description", f"子任务 {i}")
            desc_to_id[desc] = task_id
            sub_tasks.append(
                SubTask(
                    id=task_id,
                    description=desc,
                    question=t.get("question", desc),
                    depends_on=t.get("depends_on", []),
                )
            )

        # Resolve depends_on to task IDs and compute topological order
        for st in sub_tasks:
            st.depends_on[:] = [desc_to_id.get(d, d) for d in st.depends_on]

        order = _topological_sort(sub_tasks)

        return TaskPlan(
            original_question=question,
            sub_tasks=sub_tasks,
            execution_order=order,
        )


def _topological_sort(tasks: list[SubTask]) -> list[str]:
    """Simple topological sort for task dependencies."""
    task_map = {t.id: t for t in tasks}
    visited: set[str] = set()
    order: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        visited.add(task_id)
        task = task_map.get(task_id)
        if task:
            for dep in task.depends_on:
                visit(dep)
        order.append(task_id)

    for t in tasks:
        visit(t.id)
    return order
