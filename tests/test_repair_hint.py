"""Tests for the error-type-aware repair hint builder in the ReAct loop."""

from __future__ import annotations

import json

import pytest

from ai_data_agent.agent.loop import _build_repair_hint


def _obs(reasons: list[str]) -> str:
    return json.dumps({"allowed": False, "reasons": reasons})


# ---------------------------------------------------------------------------
# Sensitive field
# ---------------------------------------------------------------------------


def test_repair_hint_sensitive_id_card() -> None:
    hint = _build_repair_hint(_obs(["Query references sensitive field(s): id_card."]))
    assert "敏感" in hint or "sensitive" in hint.lower() or "id_card" in hint.lower()


def test_repair_hint_sensitive_phone() -> None:
    hint = _build_repair_hint(_obs(["Query references sensitive field(s): phone."]))
    assert "generate_sql" in hint


def test_repair_hint_sensitive_patient_name() -> None:
    hint = _build_repair_hint(_obs(["Query references sensitive field(s): patient_name."]))
    assert "generate_sql" in hint


# ---------------------------------------------------------------------------
# SELECT *
# ---------------------------------------------------------------------------


def test_repair_hint_select_star() -> None:
    hint = _build_repair_hint(_obs(["SELECT * is not allowed."]))
    assert "SELECT *" in hint or "select *" in hint.lower() or "通配符" in hint


# ---------------------------------------------------------------------------
# LIMIT
# ---------------------------------------------------------------------------


def test_repair_hint_missing_limit() -> None:
    hint = _build_repair_hint(_obs(["LIMIT is required for agent-generated SELECT queries."]))
    assert "LIMIT" in hint


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_repair_hint_schema_unqualified() -> None:
    hint = _build_repair_hint(_obs(["Table must be schema-qualified: dwd_patient"]))
    assert "Schema" in hint or "schema" in hint.lower()


def test_repair_hint_schema_not_allowed() -> None:
    hint = _build_repair_hint(_obs(["Schema is not allowed: raw"]))
    assert "Schema" in hint or "schema" in hint.lower()


# ---------------------------------------------------------------------------
# Dangerous keyword
# ---------------------------------------------------------------------------


def test_repair_hint_dangerous_drop() -> None:
    hint = _build_repair_hint(_obs(["Dangerous keyword 'DROP' is not allowed."]))
    assert "SELECT" in hint or "危险" in hint


def test_repair_hint_dangerous_delete() -> None:
    hint = _build_repair_hint(_obs(["Dangerous keyword 'DELETE' is not allowed."]))
    assert "SELECT" in hint or "危险" in hint


# ---------------------------------------------------------------------------
# Syntax / parse error
# ---------------------------------------------------------------------------


def test_repair_hint_parse_error() -> None:
    hint = _build_repair_hint(_obs(["SQL parse failed: unexpected token"]))
    assert "语法" in hint or "syntax" in hint.lower() or "generate_sql" in hint


# ---------------------------------------------------------------------------
# Default fallback
# ---------------------------------------------------------------------------


def test_repair_hint_default_when_unknown_reason() -> None:
    hint = _build_repair_hint(_obs(["Some unknown error"]))
    assert "generate_sql" in hint or "修复" in hint


def test_repair_hint_invalid_json_falls_back_to_default() -> None:
    hint = _build_repair_hint("NOT JSON AT ALL")
    assert len(hint) > 0


def test_repair_hint_empty_reasons_falls_back_to_default() -> None:
    hint = _build_repair_hint(_obs([]))
    assert len(hint) > 0
