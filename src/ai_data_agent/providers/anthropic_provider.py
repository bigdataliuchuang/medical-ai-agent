"""Anthropic SDK-based LLM provider for Claude models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_data_agent.text2sql.llm import LlmError, LlmResponse, ToolCall, ToolDefinition


@dataclass
class AnthropicProvider:
    """Native Anthropic SDK provider — uses prompt caching and tool_use blocks natively.

    Requires: pip install anthropic
    """

    api_key: str
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    timeout: int = 60
    # Enable prompt caching for system prompt (reduces cost on repeated calls)
    enable_cache: bool = True

    def complete(self, prompt: str) -> str:
        client = self._client()
        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as exc:
            raise LlmError(f"Anthropic completion failed: {exc}") from exc

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        temperature: float = 0,
    ) -> LlmResponse:
        client = self._client()

        system_content, api_messages = _split_system(messages)

        anthropic_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
            "temperature": temperature,
        }

        if system_content:
            if self.enable_cache:
                # Cache the system prompt — saves tokens on multi-turn conversations
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                kwargs["system"] = system_content

        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            raise LlmError(f"Anthropic completion failed: {exc}") from exc

        content_text: str | None = None
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        usage: dict[str, int] | None = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            }

        return LlmResponse(content=content_text, tool_calls=tool_calls, usage=usage)

    # ------------------------------------------------------------------

    def _client(self) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise LlmError(
                "anthropic package is required for AnthropicProvider. "
                "Install with: pip install anthropic"
            ) from exc
        return anthropic.Anthropic(api_key=self.api_key, timeout=float(self.timeout))


def _split_system(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Separate system messages (Anthropic uses a top-level 'system' param, not a message role)."""
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg.get("content", "")))
        else:
            rest.append(msg)
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest
