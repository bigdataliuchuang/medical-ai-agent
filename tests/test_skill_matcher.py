"""Tests for the upgraded SkillMatcher (embedding + keyword fallback)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from ai_data_agent.agent.skill_loader import (
    Skill,
    SkillMatcher,
    _cosine,
    match_skill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(name: str, keywords: list[str]) -> Skill:
    return Skill(name=name, filename=f"{name}.md", content=f"# {name}", keywords=keywords)


SKILLS = [
    _make_skill("anti_tumor_drug_usage", ["抗肿瘤", "肿瘤药", "化疗药", "靶向药"]),
    _make_skill("patient_count_analysis", ["患者数", "患者人数", "住院人次", "人数"]),
    _make_skill("drug_expense_analysis",  ["药品费用", "药费", "费用分析", "费用趋势"]),
    _make_skill("diagnosis_quality_check", ["诊断编码", "ICD", "诊断质量", "主诊断"]),
]


class FakeEmbeddingClient:
    """Returns hand-crafted vectors that make specific skills closest to specific questions."""

    # 4-dim vectors: [抗肿瘤, 患者人数, 药费, 诊断]
    _SKILL_VECS: dict[str, list[float]] = {
        "anti_tumor_drug_usage":   [0.9, 0.1, 0.3, 0.1],
        "patient_count_analysis":  [0.1, 0.9, 0.1, 0.1],
        "drug_expense_analysis":   [0.3, 0.1, 0.9, 0.1],
        "diagnosis_quality_check": [0.1, 0.1, 0.1, 0.9],
    }
    _QUESTION_VECS: dict[str, list[float]] = {
        "肺癌患者用了哪些抗肿瘤药物":  [0.85, 0.05, 0.2, 0.05],
        "本月住院患者一共多少人":       [0.05, 0.88, 0.1, 0.05],
        "各科室药品费用排名":           [0.2, 0.1, 0.85, 0.1],
        "诊断编码缺失率统计":           [0.1, 0.1, 0.1, 0.88],
    }

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            if text in self._QUESTION_VECS:
                result.append(self._QUESTION_VECS[text])
            else:
                # Match skill by checking if its name appears in text
                vec = [0.25, 0.25, 0.25, 0.25]
                for skill_name, skill_vec in self._SKILL_VECS.items():
                    if skill_name in text:
                        vec = skill_vec
                        break
                result.append(vec)
        return result


# ---------------------------------------------------------------------------
# _cosine helper
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors() -> None:
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors() -> None:
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_returns_zero() -> None:
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_partial_similarity() -> None:
    score = _cosine([1.0, 1.0], [1.0, 0.0])
    assert 0.5 < score < 1.0


# ---------------------------------------------------------------------------
# match_skill (keyword fallback, no embedding)
# ---------------------------------------------------------------------------


def test_match_skill_keyword_antitumor() -> None:
    skill = match_skill("本月抗肿瘤药物使用金额统计", SKILLS)
    assert skill is not None
    assert skill.name == "anti_tumor_drug_usage"


def test_match_skill_keyword_patient_count() -> None:
    skill = match_skill("统计本月住院患者人数", SKILLS)
    assert skill is not None
    assert skill.name == "patient_count_analysis"


def test_match_skill_keyword_no_match() -> None:
    skill = match_skill("今天天气怎么样", SKILLS)
    assert skill is None


def test_match_skill_keyword_empty_skills() -> None:
    assert match_skill("抗肿瘤药物费用", []) is None


# ---------------------------------------------------------------------------
# match_skill with embedding client
# ---------------------------------------------------------------------------


def test_match_skill_embedding_antitumor() -> None:
    skill = match_skill(
        "肺癌患者用了哪些抗肿瘤药物",
        SKILLS,
        embedding_client=FakeEmbeddingClient(),
    )
    assert skill is not None
    assert skill.name == "anti_tumor_drug_usage"


def test_match_skill_embedding_patient_count() -> None:
    skill = match_skill(
        "本月住院患者一共多少人",
        SKILLS,
        embedding_client=FakeEmbeddingClient(),
    )
    assert skill is not None
    assert skill.name == "patient_count_analysis"


def test_match_skill_embedding_drug_expense() -> None:
    skill = match_skill(
        "各科室药品费用排名",
        SKILLS,
        embedding_client=FakeEmbeddingClient(),
    )
    assert skill is not None
    assert skill.name == "drug_expense_analysis"


def test_match_skill_embedding_diagnosis() -> None:
    skill = match_skill(
        "诊断编码缺失率统计",
        SKILLS,
        embedding_client=FakeEmbeddingClient(),
    )
    assert skill is not None
    assert skill.name == "diagnosis_quality_check"


def test_match_skill_embedding_below_threshold_returns_none() -> None:
    skill = match_skill(
        "肺癌患者用了哪些抗肿瘤药物",
        SKILLS,
        embedding_client=FakeEmbeddingClient(),
        similarity_threshold=0.999,  # impossibly high
    )
    assert skill is None


# ---------------------------------------------------------------------------
# SkillMatcher — embedding caching
# ---------------------------------------------------------------------------


def test_skill_matcher_caches_embeddings() -> None:
    client = FakeEmbeddingClient()
    call_log: list[list[str]] = []
    original_embed = client.embed_texts

    def tracking_embed(texts: list[str]) -> list[list[float]]:
        call_log.append(texts)
        return original_embed(texts)

    client.embed_texts = tracking_embed  # type: ignore[method-assign]

    matcher = SkillMatcher(SKILLS, embedding_client=client)

    # First call: skill embeddings are computed once
    matcher.match("肺癌患者用了哪些抗肿瘤药物")
    calls_after_first = len(call_log)

    # Second call: skill embeddings should be cached, only question is re-embedded
    matcher.match("各科室药品费用排名")
    calls_after_second = len(call_log)

    # Each match() call embeds the question (1 call) + first time embeds all skills (1 call)
    assert calls_after_first == 2  # question + skills
    assert calls_after_second == 3  # question only (skills cached)


def test_skill_matcher_keyword_fallback() -> None:
    matcher = SkillMatcher(SKILLS)  # no embedding_client
    skill = matcher.match("本月抗肿瘤药物使用金额统计")
    assert skill is not None
    assert skill.name == "anti_tumor_drug_usage"


def test_skill_matcher_empty_skills() -> None:
    matcher = SkillMatcher([], embedding_client=FakeEmbeddingClient())
    assert matcher.match("任何问题") is None
