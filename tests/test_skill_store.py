"""Tests for SkillStore (skill accumulation layer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_agent.agent.skill_store import SkillStore


@pytest.fixture()
def store(tmp_path: Path) -> SkillStore:
    return SkillStore(db_path=str(tmp_path / "skills.db"))


def test_save_returns_record(store: SkillStore) -> None:
    rec = store.save_skill(
        question="本月肺癌患者多少人",
        sql="SELECT COUNT(*) FROM ads.ads_tumor_report_monthly WHERE tumor_type='lung'",
        tables_used=["ads.ads_tumor_report_monthly"],
        answer_summary="本月肺癌患者 120 人",
        latency_ms=500.0,
    )
    assert rec.skill_id != ""
    assert rec.success_count == 1
    assert rec.tables_used == ["ads.ads_tumor_report_monthly"]
    assert rec.avg_latency_ms == 500.0


def test_retrieve_similar_finds_match(store: SkillStore) -> None:
    store.save_skill("本月肺癌患者多少人", "SELECT 1")
    hits = store.retrieve_similar("肺癌患者本月数量")
    assert len(hits) >= 1
    assert hits[0].similarity > 0.0


def test_retrieve_returns_highest_similarity_first(store: SkillStore) -> None:
    store.save_skill("肺癌患者统计数量", "SELECT a")
    store.save_skill("肺癌患者本月总数", "SELECT b")
    hits = store.retrieve_similar("肺癌患者本月数量", top_k=2)
    assert len(hits) >= 1
    if len(hits) == 2:
        assert hits[0].similarity >= hits[1].similarity


def test_dedup_increments_success_count(store: SkillStore) -> None:
    store.save_skill("本月肺癌患者多少人", "SELECT 1", latency_ms=100.0)
    store.save_skill("本月肺癌患者多少人", "SELECT 1", latency_ms=200.0)

    hits = store.retrieve_similar("本月肺癌患者多少人")
    assert len(hits) == 1
    assert hits[0].success_count == 2


def test_dedup_updates_avg_latency(store: SkillStore) -> None:
    store.save_skill("本月肺癌患者多少人", "SELECT 1", latency_ms=100.0)
    rec = store.save_skill("本月肺癌患者多少人", "SELECT 1", latency_ms=300.0)
    assert rec.avg_latency_ms == 200.0


def test_no_match_below_threshold(store: SkillStore) -> None:
    store.save_skill("肺癌患者统计", "SELECT 1")
    hits = store.retrieve_similar("今天天气如何")
    assert hits == []


def test_top_k_limits_results(store: SkillStore) -> None:
    for i in range(6):
        store.save_skill(f"肺癌患者第{i}次查询", f"SELECT {i}")
    hits = store.retrieve_similar("肺癌患者查询", top_k=3)
    assert len(hits) <= 3


def test_empty_store_returns_no_hits(store: SkillStore) -> None:
    hits = store.retrieve_similar("任何问题")
    assert hits == []


def test_get_stats_after_saves(store: SkillStore) -> None:
    store.save_skill("Q1 肺癌", "SELECT 1", latency_ms=100.0)
    store.save_skill("Q2 MPI", "SELECT 2", latency_ms=200.0)
    stats = store.get_stats()
    assert stats["total_skills"] == 2
    assert stats["total_uses"] == 2
    assert stats["avg_latency_ms"] == 150.0


def test_get_stats_empty_store(store: SkillStore) -> None:
    stats = store.get_stats()
    assert stats["total_skills"] == 0
    assert stats["total_uses"] == 0


def test_prune_removes_old_skills(store: SkillStore) -> None:
    store.save_skill("旧查询", "SELECT 1")
    # max_age_days=-1 means cutoff is in the future, so all records are "old"
    pruned = store.prune_old_skills(min_success_count=1, max_age_days=-1.0)
    assert pruned >= 1
    assert store.get_stats()["total_skills"] == 0


def test_prune_keeps_high_success_count(store: SkillStore) -> None:
    # save twice to get success_count == 2
    store.save_skill("常用查询", "SELECT 1")
    store.save_skill("常用查询", "SELECT 1")
    pruned = store.prune_old_skills(min_success_count=1, max_age_days=-1.0)
    # success_count == 2 > min_success_count 1, so it should NOT be pruned
    assert pruned == 0


def test_tables_used_persisted(store: SkillStore) -> None:
    store.save_skill(
        "药品费用统计",
        "SELECT drug_code FROM ads.t",
        tables_used=["ads.ads_drug_usage_trend", "dws.patient"],
    )
    hits = store.retrieve_similar("药品费用统计")
    assert "ads.ads_drug_usage_trend" in hits[0].tables_used
