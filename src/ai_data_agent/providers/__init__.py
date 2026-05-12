"""LLM provider adapters — swap between Anthropic, OpenAI-compatible, and mock backends."""

from ai_data_agent.providers.factory import create_provider

__all__ = ["create_provider"]
