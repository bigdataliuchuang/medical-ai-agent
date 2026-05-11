"""Tests for the ReAct agent loop."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from ai_data_agent.agent.loop import ReActAgent
from ai_data_agent.agent.tool_impls import (
    AnalyzeResultTool,
    GenerateSqlFromContextTool,
    SearchMetadataTool,
)
from ai_data_agent.agent.tools import ToolRegistry, ToolResult
from ai_data_agent.executor.doris import DorisQueryResult
from ai_data_agent.text2sql.llm import LlmResponse, ToolCall, ToolDefinition


class StubTool:
    """A simple tool that returns a fixed result."""

    def __init__(self, name: str, output: str, success: bool = True):
        self._name = name
        self._output = output
        self._success = success

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Stub tool: {self._name}"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=self._success, output=self._output)

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )


def test_agent_returns_final_answer_directly():
    """When LLM returns only content (no tool calls), agent returns immediately."""
    llm = MagicMock()
    llm.complete_with_tools.return_value = LlmResponse(
        content="The answer is 42.",
        tool_calls=[],
    )

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("What is the answer?")

    assert trace.status == "success"
    assert trace.final_answer == "The answer is 42."
    assert len(trace.steps) == 1
    assert trace.steps[0].is_final is True
    assert trace.total_llm_calls == 1


def test_agent_executes_tool_then_returns():
    """Agent calls a tool, gets result, then returns final answer."""
    llm = MagicMock()
    # First call: tool call. Second call: final answer.
    llm.complete_with_tools.side_effect = [
        LlmResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_1", name="lookup", arguments={"q": "test"})],
        ),
        LlmResponse(content="Found it!", tool_calls=[]),
    ]

    registry = ToolRegistry()
    registry.register(StubTool("lookup", '{"result": "found"}'))
    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("Find something")

    assert trace.status == "success"
    assert trace.final_answer == "Found it!"
    assert len(trace.steps) == 2
    assert trace.steps[0].action == "lookup"
    assert trace.steps[0].is_final is False
    assert trace.steps[1].is_final is True
    assert trace.total_llm_calls == 2


def test_agent_handles_unknown_tool():
    """Agent gracefully handles LLM calling a non-existent tool."""
    llm = MagicMock()
    llm.complete_with_tools.side_effect = [
        LlmResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_1", name="nonexistent", arguments={})],
        ),
        LlmResponse(content="I couldn't use that tool.", tool_calls=[]),
    ]

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("Do something")

    assert trace.status == "success"
    assert "Unknown tool" in trace.steps[0].observation


def test_agent_max_steps_cutoff():
    """Agent stops after max_steps even if LLM keeps calling tools."""
    llm = MagicMock()
    # Always return a tool call
    llm.complete_with_tools.return_value = LlmResponse(
        content=None,
        tool_calls=[ToolCall(id="tc_1", name="loop_tool", arguments={})],
    )

    registry = ToolRegistry()
    registry.register(StubTool("loop_tool", "keep going"))
    agent = ReActAgent(llm=llm, tools=registry, max_steps=3)
    trace = agent.run("Infinite loop question")

    assert trace.status == "max_steps"
    assert len(trace.steps) == 3
    assert trace.total_llm_calls == 3


def test_agent_handles_llm_error():
    """Agent handles LLM call failure gracefully."""
    llm = MagicMock()
    llm.complete_with_tools.side_effect = Exception("Connection refused")

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("Test question")

    assert trace.status == "error"
    assert "Connection refused" in trace.steps[0].observation
    assert trace.steps[0].is_final is True


def test_agent_tracks_elapsed_time():
    """Agent records elapsed time for each step and total."""
    llm = MagicMock()
    llm.complete_with_tools.return_value = LlmResponse(
        content="Done.", tool_calls=[],
    )

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("Quick question")

    assert trace.total_elapsed_ms >= 0
    assert trace.steps[0].elapsed_ms >= 0


def test_agent_generates_request_id():
    """Agent auto-generates a request_id if not provided."""
    llm = MagicMock()
    llm.complete_with_tools.return_value = LlmResponse(content="ok", tool_calls=[])

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry)
    trace = agent.run("Test")

    assert len(trace.request_id) > 0


def test_agent_uses_provided_request_id():
    """Agent uses the provided request_id."""
    llm = MagicMock()
    llm.complete_with_tools.return_value = LlmResponse(content="ok", tool_calls=[])

    registry = ToolRegistry()
    agent = ReActAgent(llm=llm, tools=registry)
    trace = agent.run("Test", request_id="custom_id_123")

    assert trace.request_id == "custom_id_123"


def test_agent_caches_context_from_search_metadata():
    """search_metadata result is cached and passed to generate_sql."""
    fake_context = MagicMock()
    fake_sql = "SELECT drug_code FROM ads.t LIMIT 10"

    # search_metadata tool stores context in metadata
    search_tool = MagicMock(spec=SearchMetadataTool)
    search_tool.name = "search_metadata"
    search_tool.description = "search"
    search_tool.parameters_schema = {"type": "object", "properties": {}}
    search_tool.execute.return_value = ToolResult(
        success=True,
        output='{"tables": [], "metrics": [], "dq_rules": [], "join_paths": 0, "lineages": 0, "sources_count": 0}',
        metadata={"context": fake_context},
    )

    # generate_sql tool should be called via execute_with_context
    gen_tool = MagicMock(spec=GenerateSqlFromContextTool)
    gen_tool.name = "generate_sql"
    gen_tool.description = "gen"
    gen_tool.parameters_schema = {"type": "object", "properties": {}}
    gen_tool.execute_with_context.return_value = ToolResult(
        success=True,
        output=json.dumps({"sql": fake_sql}),
        metadata={"sql": fake_sql},
    )

    registry = ToolRegistry()
    registry.register(search_tool)
    registry.register(gen_tool)

    llm = MagicMock()
    llm.complete_with_tools.side_effect = [
        LlmResponse(content=None, tool_calls=[
            ToolCall(id="t1", name="search_metadata", arguments={"question": "test"}),
        ]),
        LlmResponse(content=None, tool_calls=[
            ToolCall(id="t2", name="generate_sql", arguments={"question": "test"}),
        ]),
        LlmResponse(content="Done.", tool_calls=[]),
    ]

    agent = ReActAgent(llm=llm, tools=registry, max_steps=5)
    trace = agent.run("test")

    assert trace.status == "success"
    gen_tool.execute_with_context.assert_called_once_with("test", fake_context)


def test_agent_caches_query_result_and_passes_to_analyze():
    """execute_sql result is cached and passed to analyze_result via analyze_with_context."""
    fake_context = MagicMock()
    fake_query_result = DorisQueryResult(
        columns=["drug_code", "cnt"],
        rows=[{"drug_code": "A001", "cnt": 42}],
        row_count=1,
        elapsed_ms=10,
    )

    # search_metadata stores context
    search_tool = MagicMock(spec=SearchMetadataTool)
    search_tool.name = "search_metadata"
    search_tool.description = "search"
    search_tool.parameters_schema = {"type": "object", "properties": {}}
    search_tool.execute.return_value = ToolResult(
        success=True,
        output='{"tables": [], "metrics": [], "dq_rules": [], "join_paths": 0, "lineages": 0, "sources_count": 0}',
        metadata={"context": fake_context},
    )

    # execute_sql stores query_result in metadata
    exec_tool = MagicMock()
    exec_tool.name = "execute_sql"
    exec_tool.description = "exec"
    exec_tool.parameters_schema = {"type": "object", "properties": {}}
    exec_tool.execute.return_value = ToolResult(
        success=True,
        output=json.dumps({"columns": ["drug_code", "cnt"], "rows": [], "row_count": 1, "elapsed_ms": 10}),
        metadata={"query_result": fake_query_result},
    )

    # analyze_result should receive analyze_with_context call
    analyze_tool = MagicMock(spec=AnalyzeResultTool)
    analyze_tool.name = "analyze_result"
    analyze_tool.description = "analyze"
    analyze_tool.parameters_schema = {"type": "object", "properties": {}}
    analyze_tool.analyze_with_context.return_value = ToolResult(
        success=True,
        output=json.dumps({"answer": "药品使用正常", "downstream_suggestions": []}),
    )

    registry = ToolRegistry()
    registry.register(search_tool)
    registry.register(exec_tool)
    registry.register(analyze_tool)

    llm = MagicMock()
    llm.complete_with_tools.side_effect = [
        LlmResponse(content=None, tool_calls=[
            ToolCall(id="t1", name="search_metadata", arguments={"question": "test"}),
        ]),
        LlmResponse(content=None, tool_calls=[
            ToolCall(id="t2", name="execute_sql", arguments={"sql": "SELECT drug_code FROM ads.t LIMIT 10"}),
        ]),
        LlmResponse(content=None, tool_calls=[
            ToolCall(id="t3", name="analyze_result", arguments={"question": "test", "sql": "SELECT ..."}),
        ]),
        LlmResponse(content="分析完成", tool_calls=[]),
    ]

    agent = ReActAgent(llm=llm, tools=registry, max_steps=6)
    trace = agent.run("test")

    assert trace.status == "success"
    analyze_tool.analyze_with_context.assert_called_once_with(
        question="test",
        sql="SELECT ...",
        query_result=fake_query_result,
        context=fake_context,
    )
