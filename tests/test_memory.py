"""Tests for ConversationMemory (SQLite-backed session history)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ai_data_agent.agent.memory import ConversationMemory


@pytest.fixture()
def memory(tmp_path: Path) -> ConversationMemory:
    db = tmp_path / "test_memory.db"
    return ConversationMemory(db_path=str(db), ttl_s=3600)


def test_save_and_retrieve(memory: ConversationMemory):
    turn = memory.save_turn("s1", "Q1", "A1", sql="SELECT 1")
    assert turn.turn_number == 1
    assert turn.question == "Q1"
    assert turn.answer == "A1"
    assert turn.sql == "SELECT 1"

    history = memory.get_history("s1")
    assert len(history) == 1
    assert history[0].question == "Q1"


def test_turns_are_chronological(memory: ConversationMemory):
    memory.save_turn("s1", "Q1", "A1")
    memory.save_turn("s1", "Q2", "A2")
    memory.save_turn("s1", "Q3", "A3")

    history = memory.get_history("s1")
    assert [t.question for t in history] == ["Q1", "Q2", "Q3"]


def test_turn_numbers_increment(memory: ConversationMemory):
    t1 = memory.save_turn("s1", "Q1", "A1")
    t2 = memory.save_turn("s1", "Q2", "A2")
    t3 = memory.save_turn("s2", "Q3", "A3")

    assert t1.turn_number == 1
    assert t2.turn_number == 2
    assert t3.turn_number == 1  # different session resets counter


def test_tables_used_serialization(memory: ConversationMemory):
    memory.save_turn("s1", "Q1", "A1", tables_used=["ads.drug_cost", "dws.patient"])
    history = memory.get_history("s1")
    assert history[0].tables_used == ["ads.drug_cost", "dws.patient"]


def test_tables_used_defaults_empty(memory: ConversationMemory):
    memory.save_turn("s1", "Q1", "A1")
    history = memory.get_history("s1")
    assert history[0].tables_used == []


def test_max_turns_limit(memory: ConversationMemory):
    for i in range(10):
        memory.save_turn("s1", f"Q{i}", f"A{i}")

    history = memory.get_history("s1", max_turns=3)
    assert len(history) == 3
    # Should return the 3 most recent, in chronological order
    assert history[0].question == "Q7"
    assert history[2].question == "Q9"


def test_clear_session(memory: ConversationMemory):
    memory.save_turn("s1", "Q1", "A1")
    memory.save_turn("s1", "Q2", "A2")
    memory.save_turn("s2", "Q3", "A3")

    deleted = memory.clear_session("s1")
    assert deleted == 2
    assert memory.get_history("s1") == []
    assert len(memory.get_history("s2")) == 1


def test_clear_nonexistent_session(memory: ConversationMemory):
    deleted = memory.clear_session("no_such_session")
    assert deleted == 0


def test_list_sessions(memory: ConversationMemory):
    memory.save_turn("s1", "Q1", "A1")
    memory.save_turn("s2", "Q2", "A2")
    memory.save_turn("s3", "Q3", "A3")

    sessions = memory.list_sessions()
    assert set(sessions) == {"s1", "s2", "s3"}


def test_purge_expired(memory: ConversationMemory, tmp_path: Path):
    # Create a memory with near-zero TTL
    db = tmp_path / "expiring.db"
    short_ttl = ConversationMemory(db_path=str(db), ttl_s=0.01)
    short_ttl.save_turn("s1", "Q1", "A1")
    short_ttl.save_turn("s2", "Q2", "A2")

    time.sleep(0.05)

    purged = short_ttl.purge_expired()
    assert purged == 2
    assert short_ttl.get_history("s1") == []


def test_history_for_empty_session(memory: ConversationMemory):
    history = memory.get_history("nonexistent")
    assert history == []


def test_save_turn_returns_sql_none_by_default(memory: ConversationMemory):
    turn = memory.save_turn("s1", "Q1", "A1")
    assert turn.sql is None


def test_sql_roundtrip(memory: ConversationMemory):
    sql = "SELECT drug_name, SUM(cost) FROM dws.drug GROUP BY drug_name"
    memory.save_turn("s1", "Q1", "A1", sql=sql)
    history = memory.get_history("s1")
    assert history[0].sql == sql


def test_unicode_content(memory: ConversationMemory):
    memory.save_turn("s1", "各科室费用排名", "住院患者抗肿瘤药物费用前三的科室是：肿瘤内科、血液科、呼吸科")
    history = memory.get_history("s1")
    assert history[0].question == "各科室费用排名"
    assert "肿瘤内科" in history[0].answer
