"""Deterministic mock LLM provider for unit and integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_data_agent.text2sql.llm import LlmResponse, ToolCall, ToolDefinition


@dataclass
class MockProvider:
    """Scriptable mock that returns pre-programmed responses in sequence.

    Usage::

        provider = MockProvider(responses=[
            LlmResponse(content="first answer"),
            LlmResponse(content="second answer"),
        ])
    """

    responses: list[LlmResponse] = field(default_factory=list)
    # If True, replay the last response indefinitely instead of raising StopIteration
    loop_last: bool = True

    _call_count: int = field(default=0, init=False, repr=False)

    def complete(self, prompt: str) -> str:
        resp = self._next()
        return resp.content or ""

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        temperature: float = 0,
    ) -> LlmResponse:
        return self._next()

    def _next(self) -> LlmResponse:
        if not self.responses:
            return LlmResponse(content="mock response")
        idx = self._call_count
        if idx >= len(self.responses):
            if self.loop_last:
                idx = len(self.responses) - 1
            else:
                raise StopIteration("MockProvider exhausted all scripted responses")
        self._call_count += 1
        return self.responses[idx]

    @property
    def call_count(self) -> int:
        return self._call_count
