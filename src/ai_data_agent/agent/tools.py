"""Tool abstraction and registry for the Data Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_data_agent.text2sql.llm import ToolDefinition


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool execution."""

    success: bool
    output: str  # JSON-serialized result or error message
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    """A callable unit the agent can invoke."""

    @property
    def name(self) -> str:
        """Unique tool identifier."""

    @property
    def description(self) -> str:
        """Human-readable description for the LLM."""

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input parameters."""

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Run the tool with the given arguments."""


class ToolRegistry:
    """Registry of tools available to the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters_schema,
            )
            for tool in self._tools.values()
        ]

    def names(self) -> list[str]:
        return list(self._tools.keys())
