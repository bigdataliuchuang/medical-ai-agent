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
