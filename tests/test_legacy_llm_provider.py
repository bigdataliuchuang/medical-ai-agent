import importlib
import sys
from types import SimpleNamespace


def test_legacy_sql_gen_supports_openai_compatible_without_anthropic(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_openai = SimpleNamespace(OpenAI=FakeOpenAI, AsyncOpenAI=FakeAsyncOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.delitem(sys.modules, "anthropic", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen-plus")
    sys.modules.pop("agent.sql_gen", None)

    sql_gen = importlib.import_module("agent.sql_gen")

    assert sql_gen.generate_sql_with_prompt("system", [{"role": "user", "content": "hi"}]) == "SELECT 1"
