"""LLM client contract for Text-to-SQL generation."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


class LlmError(RuntimeError):
    """Raised when LLM completion fails."""


@dataclass(frozen=True)
class ToolDefinition:
    """Schema for a tool the LLM can invoke."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LlmResponse:
    """Structured response from an LLM call."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] | None = None  # {"prompt_tokens": N, "completion_tokens": N}


class LlmClient(Protocol):
    def complete(self, prompt: str) -> str:
        """Generate a completion for the prompt."""

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        temperature: float = 0,
    ) -> LlmResponse:
        """Generate a completion with tool-calling support."""


@dataclass(frozen=True)
class OpenAICompatibleLlmClient:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    def complete(self, prompt: str) -> str:
        request = urllib.request.Request(
            url=self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(
                {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You generate safe Doris SQL from curated metadata context.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        choices = payload.get("choices")
        if not choices:
            raise LlmError("LLM response missing choices.")
        content = choices[0].get("message", {}).get("content")
        if not content:
            raise LlmError("LLM response missing message content.")
        return content

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        temperature: float = 0,
    ) -> LlmResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        request = urllib.request.Request(
            url=self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        choices = payload.get("choices")
        if not choices:
            raise LlmError("LLM response missing choices.")

        message = choices[0].get("message", {})
        content = message.get("content")
        raw_tool_calls = message.get("tool_calls") or []

        parsed_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                )
            )

        usage = payload.get("usage")

        return LlmResponse(
            content=content,
            tool_calls=parsed_calls,
            usage=usage,
        )
