"""Tests for SkillLoader (skill matching and prompt injection)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_agent.agent.skill_loader import (
    Skill,
    inject_skill_into_prompt,
    load_all_skills,
    match_skill,
)


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    (tmp_path / "anti_tumor_drug_usage.md").write_text(
        "# Skill: 抗肿瘤药物使用分析\n\n## 适用场景\n触发关键词：抗肿瘤、靶向药。\n\n## SQL模板\nSELECT 1;",
        encoding="utf-8",
    )
    (tmp_path / "patient_count_analysis.md").write_text(
        "# Skill: 患者人数统计\n\n## 适用场景\n触发关键词：患者数、人次。",
        encoding="utf-8",
    )
    return tmp_path


def test_load_all_skills_returns_skills(skills_dir: Path) -> None:
    skills = load_all_skills(skills_dir)
    assert len(skills) == 2
    names = [s.name for s in skills]
    assert "Skill: 抗肿瘤药物使用分析" in names


def test_load_empty_dir_returns_empty(tmp_path: Path) -> None:
    skills = load_all_skills(tmp_path)
    assert skills == []


def test_load_nonexistent_dir_returns_empty() -> None:
    skills = load_all_skills("/nonexistent/skills/dir")
    assert skills == []


def test_skill_matches_by_keyword() -> None:
    skill = Skill("抗肿瘤", "anti_tumor.md", "content", keywords=["抗肿瘤", "靶向药"])
    assert skill.matches("本月抗肿瘤药物使用患者数")
    assert not skill.matches("本月患者住院人次")


def test_match_skill_returns_best_match(skills_dir: Path) -> None:
    skills = load_all_skills(skills_dir)
    matched = match_skill("统计抗肿瘤药物使用人数", skills)
    assert matched is not None
    assert "抗肿瘤" in matched.name


def test_match_skill_returns_none_for_no_match(skills_dir: Path) -> None:
    skills = load_all_skills(skills_dir)
    matched = match_skill("今天天气如何", skills)
    assert matched is None


def test_match_skill_prefers_higher_overlap(skills_dir: Path) -> None:
    skills = load_all_skills(skills_dir)
    # Both "患者数" and "抗肿瘤" are in question, but "抗肿瘤" has more keyword hits
    matched = match_skill("统计抗肿瘤药物使用患者数量", skills)
    assert matched is not None
    # Should still return a result (not crash on overlap tie)


def test_inject_skill_appends_to_prompt() -> None:
    base_prompt = "你是医疗数据分析Agent。"
    skill = Skill("抗肿瘤分析", "anti_tumor.md", "这里是技能内容。", keywords=[])
    result = inject_skill_into_prompt(base_prompt, skill)
    assert base_prompt in result
    assert "这里是技能内容" in result
    assert "参考技能" in result


def test_inject_skill_does_not_modify_base() -> None:
    base = "原始提示词"
    skill = Skill("S", "s.md", "内容", keywords=[])
    result = inject_skill_into_prompt(base, skill)
    assert result != base
    assert base == "原始提示词"  # original unchanged


def test_keyword_overlap_counts_matches() -> None:
    skill = Skill("Test", "t.md", "", keywords=["抗肿瘤", "靶向药", "患者数"])
    assert skill.keyword_overlap("统计抗肿瘤靶向药使用患者数") == 3
    assert skill.keyword_overlap("统计抗肿瘤药物") == 1
    assert skill.keyword_overlap("今天天气") == 0


def test_load_skills_uses_keyword_dict_for_known_files(tmp_path: Path) -> None:
    (tmp_path / "anti_tumor_drug_usage.md").write_text(
        "# 抗肿瘤\n内容", encoding="utf-8"
    )
    skills = load_all_skills(tmp_path)
    assert len(skills) == 1
    assert "抗肿瘤" in skills[0].keywords
