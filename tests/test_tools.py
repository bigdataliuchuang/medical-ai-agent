"""Tests for tool infrastructure."""

from __future__ import annotations

from typing import Any

from ai_data_agent.agent.tools import ToolRegistry, ToolResult
from ai_data_agent.text2sql.llm import ToolDefinition


class StubTool:
    """A minimal tool for testing the registry."""

    def __init__(self, name: str = "stub", description: str = "A stub tool"):
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="ok")

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )


class PropertyOnlyTool:
    """A tool shaped like the concrete agent tools."""

    @property
    def name(self) -> str:
        return "property_only"

    @property
    def description(self) -> str:
        return "A tool described through properties."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="ok")


def test_tool_registry_register_and_get():
    registry = ToolRegistry()
    tool = StubTool("my_tool")
    registry.register(tool)
    assert registry.get("my_tool") is tool
    assert registry.get("nonexistent") is None


def test_tool_registry_definitions():
    registry = ToolRegistry()
    registry.register(StubTool("tool_a", "Tool A"))
    registry.register(StubTool("tool_b", "Tool B"))
    defs = registry.definitions()
    assert len(defs) == 2
    assert defs[0].name == "tool_a"
    assert defs[1].name == "tool_b"
    assert all(isinstance(d, ToolDefinition) for d in defs)


def test_tool_registry_builds_definitions_from_tool_properties():
    registry = ToolRegistry()
    registry.register(PropertyOnlyTool())

    defs = registry.definitions()

    assert defs == [
        ToolDefinition(
            name="property_only",
            description="A tool described through properties.",
            parameters={"type": "object", "properties": {}},
        )
    ]


def test_tool_registry_names():
    registry = ToolRegistry()
    registry.register(StubTool("alpha"))
    registry.register(StubTool("beta"))
    assert registry.names() == ["alpha", "beta"]


def test_tool_registry_empty():
    registry = ToolRegistry()
    assert registry.definitions() == []
    assert registry.names() == []
    assert registry.get("anything") is None


def test_tool_result_success():
    result = ToolResult(success=True, output='{"count": 42}')
    assert result.success is True
    assert result.output == '{"count": 42}'
    assert result.metadata == {}


def test_tool_result_failure_with_metadata():
    result = ToolResult(
        success=False,
        output="error",
        metadata={"code": "TIMEOUT"},
    )
    assert result.success is False
    assert result.metadata["code"] == "TIMEOUT"
