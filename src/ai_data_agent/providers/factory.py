"""Factory for creating LLM providers from a config string."""

from __future__ import annotations

from typing import Any

from ai_data_agent.text2sql.llm import LlmClient, OpenAICompatibleLlmClient

_SUPPORTED = ("anthropic", "openai", "openai_compatible", "mock")


def create_provider(provider_type: str, **kwargs: Any) -> LlmClient:
    """Instantiate an LLM provider by name.

    Args:
        provider_type: One of ``"anthropic"``, ``"openai"``,
            ``"openai_compatible"``, or ``"mock"`` (tests only).
        **kwargs: Provider-specific keyword arguments forwarded to the
            corresponding class constructor.

    Returns:
        An object satisfying the :class:`~ai_data_agent.text2sql.llm.LlmClient`
        protocol.

    Raises:
        ValueError: If *provider_type* is not recognised.
    """
    match provider_type:
        case "anthropic":
            from ai_data_agent.providers.anthropic_provider import AnthropicProvider

            return AnthropicProvider(**kwargs)
        case "openai" | "openai_compatible":
            return OpenAICompatibleLlmClient(**kwargs)
        case "mock":
            from ai_data_agent.providers.mock_provider import MockProvider

            return MockProvider(**kwargs)
        case _:
            raise ValueError(
                f"Unknown provider type: {provider_type!r}. "
                f"Supported types: {', '.join(_SUPPORTED)}."
            )
