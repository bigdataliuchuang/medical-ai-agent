"""Tests for the LLM provider adapter layer."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_data_agent.providers.factory import create_provider
from ai_data_agent.providers.mock_provider import MockProvider
from ai_data_agent.text2sql.llm import LlmError, LlmResponse, ToolCall, ToolDefinition


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


def test_mock_provider_returns_scripted_responses() -> None:
    provider = MockProvider(
        responses=[
            LlmResponse(content="answer one"),
            LlmResponse(content="answer two"),
        ]
    )
    assert provider.complete("q1") == "answer one"
    assert provider.complete("q2") == "answer two"


def test_mock_provider_loops_last_response() -> None:
    provider = MockProvider(
        responses=[LlmResponse(content="only")],
        loop_last=True,
    )
    for _ in range(5):
        assert provider.complete("x") == "only"


def test_mock_provider_raises_when_exhausted_and_no_loop() -> None:
    provider = MockProvider(
        responses=[LlmResponse(content="once")],
        loop_last=False,
    )
    provider.complete("first")
    with pytest.raises(StopIteration):
        provider.complete("second")


def test_mock_provider_empty_returns_default() -> None:
    provider = MockProvider()
    assert provider.complete("anything") == "mock response"


def test_mock_provider_tracks_call_count() -> None:
    provider = MockProvider(responses=[LlmResponse(content="x")])
    provider.complete("a")
    provider.complete("b")
    assert provider.call_count == 2


def test_mock_provider_complete_with_tools_returns_tool_calls() -> None:
    tool_call = ToolCall(id="t1", name="search_metadata", arguments={"question": "肺癌"})
    provider = MockProvider(responses=[LlmResponse(content=None, tool_calls=[tool_call])])
    tools = [ToolDefinition(name="search_metadata", description="...", parameters={})]
    resp = provider.complete_with_tools([{"role": "user", "content": "hi"}], tools)
    assert resp.tool_calls[0].name == "search_metadata"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_creates_openai_compatible_provider() -> None:
    provider = create_provider(
        "openai_compatible",
        base_url="http://localhost:8080",
        api_key="key",
        model="gpt-4o",
    )
    from ai_data_agent.text2sql.llm import OpenAICompatibleLlmClient

    assert isinstance(provider, OpenAICompatibleLlmClient)


def test_factory_creates_openai_alias() -> None:
    provider = create_provider(
        "openai",
        base_url="http://localhost:8080",
        api_key="key",
        model="gpt-4o",
    )
    from ai_data_agent.text2sql.llm import OpenAICompatibleLlmClient

    assert isinstance(provider, OpenAICompatibleLlmClient)


def test_factory_creates_mock_provider() -> None:
    provider = create_provider("mock")
    assert isinstance(provider, MockProvider)


def test_factory_creates_anthropic_provider() -> None:
    from ai_data_agent.providers.anthropic_provider import AnthropicProvider

    provider = create_provider("anthropic", api_key="sk-test", model="claude-haiku-4-5-20251001")
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-haiku-4-5-20251001"


def test_factory_raises_on_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider type"):
        create_provider("nonexistent_llm")


# ---------------------------------------------------------------------------
# AnthropicProvider (mocked SDK)
# ---------------------------------------------------------------------------


def _make_fake_anthropic(text_content: str | None = "ok", tool_calls: list | None = None):
    """Build a minimal fake anthropic module."""

    @dataclass
    class FakeUsage:
        input_tokens: int = 10
        output_tokens: int = 5

    @dataclass
    class FakeTextBlock:
        type: str = "text"
        text: str = text_content or ""

    @dataclass
    class FakeToolUseBlock:
        type: str = "tool_use"
        id: str = "tu_1"
        name: str = "search_metadata"
        input: dict = field(default_factory=lambda: {"question": "test"})

    @dataclass
    class FakeMessage:
        content: list
        usage: FakeUsage = field(default_factory=FakeUsage)

    content_blocks: list = []
    if text_content is not None:
        content_blocks.append(FakeTextBlock())
    for tc in tool_calls or []:
        content_blocks.append(FakeToolUseBlock(**tc))

    fake_message = FakeMessage(content=content_blocks)

    class FakeMessages:
        def create(self, **kwargs: Any) -> FakeMessage:
            return fake_message

    class FakeAnthropic:
        def __init__(self, api_key: str, timeout: float = 60):
            self.messages = FakeMessages()

    fake_module = types.SimpleNamespace(Anthropic=FakeAnthropic)
    return fake_module


def test_anthropic_provider_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", _make_fake_anthropic("hello world"))
    from ai_data_agent.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-test")
    result = provider.complete("tell me about lung cancer patients")
    assert result == "hello world"


def test_anthropic_provider_complete_with_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        _make_fake_anthropic(
            text_content=None,
            tool_calls=[{"type": "tool_use", "id": "tu_1", "name": "search_metadata", "input": {"question": "肺癌"}}],
        ),
    )
    from importlib import reload

    import ai_data_agent.providers.anthropic_provider as mod

    reload(mod)

    provider = mod.AnthropicProvider(api_key="sk-test")
    tools = [ToolDefinition(name="search_metadata", description="...", parameters={})]
    resp = provider.complete_with_tools(
        [{"role": "system", "content": "You are a medical agent."},
         {"role": "user", "content": "肺癌患者人数"}],
        tools,
    )
    assert resp.tool_calls[0].name == "search_metadata"
    assert resp.tool_calls[0].arguments == {"question": "肺癌"}


def test_anthropic_provider_raises_when_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # simulate missing package
    from importlib import reload

    import ai_data_agent.providers.anthropic_provider as mod

    reload(mod)
    provider = mod.AnthropicProvider(api_key="sk-test")

    with pytest.raises(LlmError, match="anthropic package is required"):
        provider.complete("test")


def test_anthropic_provider_extracts_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", _make_fake_anthropic("result"))
    from importlib import reload

    import ai_data_agent.providers.anthropic_provider as mod

    reload(mod)
    provider = mod.AnthropicProvider(api_key="sk-test")
    resp = provider.complete_with_tools([{"role": "user", "content": "q"}], [])
    assert resp.usage is not None
    assert resp.usage["prompt_tokens"] == 10
    assert resp.usage["completion_tokens"] == 5


def test_anthropic_provider_system_prompt_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """System message must be extracted and sent as top-level 'system' param."""
    captured: dict = {}

    @dataclass
    class CapturingMessages:
        def create(self, **kwargs: Any):
            captured.update(kwargs)

            @dataclass
            class R:
                content: list = field(default_factory=list)
                usage: Any = None

            return R()

    class FakeAnthropic:
        def __init__(self, api_key: str, timeout: float = 60):
            self.messages = CapturingMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    from importlib import reload

    import ai_data_agent.providers.anthropic_provider as mod

    reload(mod)
    provider = mod.AnthropicProvider(api_key="sk-test", enable_cache=False)
    provider.complete_with_tools(
        [
            {"role": "system", "content": "You are a medical agent."},
            {"role": "user", "content": "肺癌"},
        ],
        [],
    )
    assert captured.get("system") == "You are a medical agent."
    # system message must NOT appear in the messages list
    for msg in captured.get("messages", []):
        assert msg.get("role") != "system"
