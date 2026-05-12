"""Compatibility tests for the legacy FastAPI SQL guard."""

from __future__ import annotations

import importlib
import sys

from sqlglot import exp


def test_legacy_sql_guard_imports_when_optional_sqlglot_nodes_are_missing(monkeypatch):
    """Some sqlglot versions do not expose every DDL expression class."""
    sys.modules.pop("agent.sql_guard", None)
    monkeypatch.delattr(exp, "Alter", raising=False)

    module = importlib.import_module("agent.sql_guard")

    assert module.validate("SELECT data_layer FROM ads_dq_result_summary LIMIT 10")["valid"] is True
