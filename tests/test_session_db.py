"""Tests for SessionDB (5-table SQLite observability store)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_agent.storage.session_db import (
    EvalResultRecord,
    SessionDB,
    SqlAuditRecord,
    ToolCallRecord,
)


@pytest.fixture()
def db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=str(tmp_path / "agent_runs.db"))


# ------------------------------------------------------------------
# agent_session
# ------------------------------------------------------------------


def test_create_session(db: SessionDB) -> None:
    db.create_session("s1", user_id="u1")
    session = db.get_session("s1")
    assert session is not None
    assert session["session_id"] == "s1"
    assert session["user_id"] == "u1"
    assert session["turn_count"] == 0


def test_create_session_idempotent(db: SessionDB) -> None:
    db.create_session("s1")
    db.create_session("s1")  # should not raise
    assert db.get_session("s1") is not None


def test_touch_session_increments_turn(db: SessionDB) -> None:
    db.create_session("s1")
    db.touch_session("s1")
    db.touch_session("s1")
    session = db.get_session("s1")
    assert session["turn_count"] == 2


def test_get_session_returns_none_for_unknown(db: SessionDB) -> None:
    assert db.get_session("nonexistent") is None


# ------------------------------------------------------------------
# agent_message
# ------------------------------------------------------------------


def test_log_and_retrieve_messages(db: SessionDB) -> None:
    db.log_message("s1", "r1", "user", "患者数是多少")
    db.log_message("s1", "r1", "assistant", "本月住院患者 120 人")
    msgs = db.get_messages("s1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["content"] == "本月住院患者 120 人"


def test_messages_scoped_to_session(db: SessionDB) -> None:
    db.log_message("s1", "r1", "user", "问题A")
    db.log_message("s2", "r2", "user", "问题B")
    assert len(db.get_messages("s1")) == 1
    assert len(db.get_messages("s2")) == 1


# ------------------------------------------------------------------
# agent_tool_call
# ------------------------------------------------------------------


def test_log_and_retrieve_tool_call(db: SessionDB) -> None:
    record = ToolCallRecord(
        session_id="s1",
        request_id="r1",
        step_number=1,
        tool_name="search_metadata",
        tool_args={"question": "肺癌患者"},
        tool_result='{"tables": ["dwd.dwd_diagnosis"]}',
        status="success",
        error_msg=None,
        elapsed_ms=120,
    )
    db.log_tool_call(record)
    calls = db.get_tool_calls("s1")
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "search_metadata"
    assert calls[0]["status"] == "success"
    assert calls[0]["elapsed_ms"] == 120


def test_tool_call_error_recorded(db: SessionDB) -> None:
    record = ToolCallRecord(
        session_id="s1",
        request_id="r1",
        step_number=2,
        tool_name="execute_sql",
        tool_args={"sql": "SELECT 1"},
        tool_result="",
        status="error",
        error_msg="Connection refused",
        elapsed_ms=5,
    )
    db.log_tool_call(record)
    calls = db.get_tool_calls("s1")
    assert calls[0]["error_msg"] == "Connection refused"


# ------------------------------------------------------------------
# agent_sql_audit
# ------------------------------------------------------------------


def test_log_sql_audit_allowed(db: SessionDB) -> None:
    record = SqlAuditRecord(
        session_id="s1",
        request_id="r1",
        sql_text="SELECT COUNT(DISTINCT mpi_id) FROM dwd.dwd_visit WHERE stat_date='2025-01' LIMIT 1",
        used_tables=["dwd.dwd_visit"],
        has_sensitive_field=False,
        sensitive_fields=[],
        risk_level="LOW",
        check_result="allowed",
        reject_reason=None,
    )
    db.log_sql_audit(record)
    audits = db.get_sql_audits("s1")
    assert len(audits) == 1
    assert audits[0]["check_result"] == "allowed"
    assert audits[0]["risk_level"] == "LOW"


def test_log_sql_audit_rejected_sensitive(db: SessionDB) -> None:
    record = SqlAuditRecord(
        session_id="s1",
        request_id="r1",
        sql_text="SELECT id_card FROM dwd.dwd_patient LIMIT 10",
        used_tables=["dwd.dwd_patient"],
        has_sensitive_field=True,
        sensitive_fields=["id_card"],
        risk_level="HIGH",
        check_result="rejected",
        reject_reason="Sensitive field: id_card",
    )
    db.log_sql_audit(record)
    high_risk = db.get_high_risk_audits()
    assert len(high_risk) == 1
    assert high_risk[0]["risk_level"] == "HIGH"


# ------------------------------------------------------------------
# agent_eval_result
# ------------------------------------------------------------------


def test_log_eval_result_and_summary(db: SessionDB) -> None:
    for i, (valid, safe, match) in enumerate([(True, True, True), (True, False, False), (False, False, False)]):
        db.log_eval_result(
            EvalResultRecord(
                eval_run_id="run_001",
                question_id=f"q{i:03d}",
                question=f"问题{i}",
                generated_sql=f"SELECT {i} FROM ads.t WHERE stat_month='2025-01' LIMIT 1",
                expected_tables=["ads.t"],
                actual_tables=["ads.t"] if match else ["wrong.t"],
                table_match=match,
                sql_valid=valid,
                sql_safe=safe,
                elapsed_ms=100 * i,
            )
        )

    summary = db.get_eval_summary("run_001")
    assert summary["total"] == 3
    assert summary["sql_valid_rate"] == pytest.approx(2 / 3, rel=0.01)
    assert summary["sql_safe_rate"] == pytest.approx(1 / 3, rel=0.01)
    assert summary["table_match_rate"] == pytest.approx(1 / 3, rel=0.01)


def test_eval_summary_empty_run(db: SessionDB) -> None:
    summary = db.get_eval_summary("nonexistent_run")
    assert summary["total"] == 0
    assert summary["sql_valid_rate"] == 0.0
