"""ReAct agent loop for multi-step reasoning and tool calling."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ai_data_agent.agent.memory import ConversationTurn
from ai_data_agent.agent.tools import ToolRegistry, ToolResult
from ai_data_agent.executor.doris import DorisQueryResult
from ai_data_agent.graphrag.context_builder import TextToSqlContext
from ai_data_agent.text2sql.llm import LlmClient, LlmResponse, ToolDefinition

# Repair hint injected into the message stream after a failed validate_sql call
_REPAIR_HINTS: dict[str, str] = {
    "sensitive": (
        "【修复提示】SQL 包含敏感字段（如 id_card / phone / patient_name）。"
        "请重新调用 generate_sql，将敏感字段从 SELECT 列表和 WHERE 条件中全部移除。"
    ),
    "select_star": (
        "【修复提示】SQL 使用了 SELECT *，不符合安全规则。"
        "请重新调用 generate_sql，明确列出需要的字段名，不要使用通配符。"
    ),
    "limit": (
        "【修复提示】SQL 缺少 LIMIT 子句。"
        "请重新调用 generate_sql，在 SQL 末尾添加 LIMIT 100（或更小的值）。"
    ),
    "schema": (
        "【修复提示】表名缺少 Schema 限定（如 dwd.dwd_order）或使用了不允许的 Schema。"
        "请重新调用 generate_sql，确保所有表名都带有 Schema 前缀。"
    ),
    "dangerous": (
        "【修复提示】SQL 包含危险关键词（DROP / DELETE / UPDATE 等），不允许执行。"
        "请只生成 SELECT 查询。"
    ),
    "syntax": (
        "【修复提示】SQL 语法错误，无法解析。"
        "请重新调用 generate_sql，生成语法正确的 SQL。"
    ),
    "default": (
        "【修复提示】SQL 未通过安全校验。请根据上方 reasons 中的原因重新调用 generate_sql 修复 SQL。"
    ),
}


_DEFAULT_SYSTEM_PROMPT = (
    "你是医疗数据治理平台的 Data Agent，负责回答用户的数据分析问题。\n"
    "你可以使用以下工具来完成任务：\n"
    "- search_metadata: 搜索元数据目录，找到相关的表、指标、DQ 规则和 Join 路径\n"
    "- generate_sql: 基于元数据上下文生成 SQL 查询\n"
    "- validate_sql: 验证 SQL 是否符合安全规则\n"
    "- execute_sql: 执行已验证的 SQL 查询\n"
    "- analyze_result: 分析查询结果，生成业务洞察\n"
    "\n"
    "工作流程：\n"
    "1. 先用 search_metadata 找到相关元数据\n"
    "2. 用 generate_sql 生成 SQL\n"
    "3. 如果 SQL 验证失败，根据错误原因修复 SQL 并重新验证\n"
    "4. 用 execute_sql 执行查询\n"
    "5. 用 analyze_result 分析结果\n"
    "\n"
    "当所有步骤完成，输出最终答案。不要编造数据。"
)


@dataclass(frozen=True)
class AgentStep:
    """A single step in the agent's reasoning trace."""

    step_number: int
    thought: str | None
    action: str | None  # tool name
    action_input: dict[str, Any] | None
    observation: str | None
    is_final: bool
    elapsed_ms: int


@dataclass(frozen=True)
class AgentTrace:
    """Complete trace of an agent execution."""

    request_id: str
    question: str
    steps: list[AgentStep]
    final_answer: str | None
    final_sql: str | None
    status: str  # "success" | "max_steps" | "error"
    total_elapsed_ms: int
    total_llm_calls: int


class ReActAgent:
    """Agent that uses ReAct pattern: Thought → Action → Observation → ... → Answer."""

    def __init__(
        self,
        llm: LlmClient,
        tools: ToolRegistry,
        max_steps: int = 8,
        system_prompt: str | None = None,
    ):
        self._llm = llm
        self._tools = tools
        self._max_steps = max_steps
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self._last_context: TextToSqlContext | None = None
        self._last_query_result: DorisQueryResult | None = None

    def run(
        self,
        question: str,
        request_id: str | None = None,
        conversation_history: list[ConversationTurn] | None = None,
    ) -> AgentTrace:
        request_id = request_id or uuid.uuid4().hex[:16]
        started = time.monotonic()
        steps: list[AgentStep] = []
        llm_calls = 0

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
        ]

        for turn in conversation_history or []:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})

        messages.append({"role": "user", "content": question})
        tool_defs = self._tools.definitions()

        for step_num in range(1, self._max_steps + 1):
            step_started = time.monotonic()

            try:
                response = self._llm.complete_with_tools(messages, tool_defs)
                llm_calls += 1
            except Exception as exc:
                elapsed = int((time.monotonic() - step_started) * 1000)
                steps.append(
                    AgentStep(
                        step_number=step_num,
                        thought=None,
                        action=None,
                        action_input=None,
                        observation=f"LLM call failed: {exc}",
                        is_final=True,
                        elapsed_ms=elapsed,
                    )
                )
                return AgentTrace(
                    request_id=request_id,
                    question=question,
                    steps=steps,
                    final_answer=None,
                    final_sql=None,
                    status="error",
                    total_elapsed_ms=int((time.monotonic() - started) * 1000),
                    total_llm_calls=llm_calls,
                )

            # No tool calls → this is the final answer
            if not response.tool_calls:
                elapsed = int((time.monotonic() - step_started) * 1000)
                steps.append(
                    AgentStep(
                        step_number=step_num,
                        thought=response.content,
                        action=None,
                        action_input=None,
                        observation=None,
                        is_final=True,
                        elapsed_ms=elapsed,
                    )
                )
                return AgentTrace(
                    request_id=request_id,
                    question=question,
                    steps=steps,
                    final_answer=response.content,
                    final_sql=self._extract_final_sql(steps),
                    status="success",
                    total_elapsed_ms=int((time.monotonic() - started) * 1000),
                    total_llm_calls=llm_calls,
                )

            # Execute tool calls
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
            )

            for tc in response.tool_calls:
                tool_started = time.monotonic()
                tool_result = self._execute_tool(tc.name, tc.arguments)
                tool_elapsed = int((time.monotonic() - tool_started) * 1000)

                steps.append(
                    AgentStep(
                        step_number=step_num,
                        thought=response.content,
                        action=tc.name,
                        action_input=tc.arguments,
                        observation=tool_result.output,
                        is_final=False,
                        elapsed_ms=tool_elapsed,
                    )
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result.output,
                    }
                )

                # After a failed validate_sql, inject a targeted repair hint so the
                # LLM knows exactly what to fix rather than guessing from the raw reasons.
                if tc.name == "validate_sql" and not tool_result.success:
                    hint = _build_repair_hint(tool_result.output)
                    messages.append({"role": "user", "content": hint})

        # Max steps reached
        return AgentTrace(
            request_id=request_id,
            question=question,
            steps=steps,
            final_answer=None,
            final_sql=self._extract_final_sql(steps),
            status="max_steps",
            total_elapsed_ms=int((time.monotonic() - started) * 1000),
            total_llm_calls=llm_calls,
        )

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name, with special handling for context-dependent tools."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, output=f"Unknown tool: {name}")

        # Special handling for generate_sql: pass the stored context
        if name == "generate_sql" and self._last_context is not None:
            from ai_data_agent.agent.tool_impls import GenerateSqlFromContextTool

            if isinstance(tool, GenerateSqlFromContextTool):
                return tool.execute_with_context(
                    arguments.get("question", ""), self._last_context
                )

        # Special handling for analyze_result: pass stored context and query result
        if name == "analyze_result" and self._last_context is not None and self._last_query_result is not None:
            from ai_data_agent.agent.tool_impls import AnalyzeResultTool

            if isinstance(tool, AnalyzeResultTool):
                return tool.analyze_with_context(
                    question=arguments.get("question", ""),
                    sql=arguments.get("sql", ""),
                    query_result=self._last_query_result,
                    context=self._last_context,
                )

        result = tool.execute(arguments)

        # Store context from search_metadata for later use
        if name == "search_metadata" and result.success:
            ctx = result.metadata.get("context")
            if ctx is not None:
                self._last_context = ctx

        # Store query result from execute_sql for analyze_result
        if name == "execute_sql" and result.success:
            qr = result.metadata.get("query_result")
            if qr is not None:
                self._last_query_result = qr

        return result

    @staticmethod
    def _extract_final_sql(steps: list[AgentStep]) -> str | None:
        """Extract the last successfully generated SQL from the trace."""
        for step in reversed(steps):
            if step.action == "generate_sql" and step.observation:
                try:
                    data = json.loads(step.observation)
                    if "sql" in data:
                        return data["sql"]
                except (json.JSONDecodeError, TypeError):
                    pass
            if step.action == "execute_sql" and step.action_input:
                return step.action_input.get("sql")
        return None


# ---------------------------------------------------------------------------
# Repair hint builder
# ---------------------------------------------------------------------------

def _build_repair_hint(validate_sql_output: str) -> str:
    """Build a targeted repair hint from a failed validate_sql observation.

    Parses the JSON output of ValidateSqlTool and picks the most specific hint
    from _REPAIR_HINTS so the LLM knows exactly what to fix next.
    """
    try:
        data = json.loads(validate_sql_output)
        reasons: list[str] = data.get("reasons", [])
    except (json.JSONDecodeError, TypeError):
        return _REPAIR_HINTS["default"]

    combined = " ".join(reasons).lower()

    if any(sf in combined for sf in ("sensitive", "id_card", "phone", "patient_name", "敏感")):
        return _REPAIR_HINTS["sensitive"]
    if "select *" in combined or "select * is not allowed" in combined:
        return _REPAIR_HINTS["select_star"]
    if "limit" in combined:
        return _REPAIR_HINTS["limit"]
    if "schema" in combined or "schema-qualified" in combined or "schema is not allowed" in combined:
        return _REPAIR_HINTS["schema"]
    if any(kw in combined for kw in ("drop", "delete", "update", "insert", "dangerous", "keyword")):
        return _REPAIR_HINTS["dangerous"]
    if "parse" in combined or "syntax" in combined:
        return _REPAIR_HINTS["syntax"]

    return _REPAIR_HINTS["default"]
