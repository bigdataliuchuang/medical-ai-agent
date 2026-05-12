"""Skill loading and matching: inject domain SOPs into the agent system prompt."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_data_agent.graphrag.embedding import EmbeddingClient

# Default location relative to the project root
_DEFAULT_SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "skills"

# Keywords that trigger each skill file (filename → keyword list)
_SKILL_KEYWORDS: dict[str, list[str]] = {
    "anti_tumor_drug_usage": [
        "抗肿瘤", "肿瘤药", "靶向药", "免疫药", "化疗药", "生物制剂", "抗癌",
        "antitumor", "tumor drug",
    ],
    "diagnosis_quality_check": [
        "诊断编码", "icd", "ICD", "诊断缺失", "诊断质量", "主诊断", "诊断映射",
        "diagnosis", "DQ-01",
    ],
    "visit_quality_check": [
        "就诊质量", "就诊数据", "入院时间", "出院时间", "时间逻辑", "visit_id",
        "就诊关联", "住院天数", "入院晚于出院",
    ],
    "patient_count_analysis": [
        "患者数", "患者人数", "就诊人次", "住院人次", "门诊人次", "患者统计",
        "人数", "patient count",
    ],
    "drug_expense_analysis": [
        "药品费用", "药费", "费用分析", "费用占比", "费用排名", "费用趋势",
        "费用结构", "drug expense",
    ],
    "lab_abnormal_analysis": [
        "检验异常", "检验结果", "危急值", "异常指标", "化验", "实验室",
        "检验报告", "lab", "abnormal",
    ],
    "dwd_table_design": [
        "DWD", "dwd", "建模", "表设计", "字段定义", "明细层", "数据分层",
        "ODS", "DWS", "表结构", "mpi_id", "visit_id和",
    ],
    "sql_optimization": [
        "SQL慢", "查询慢", "优化", "性能", "索引", "分区", "执行计划",
        "超时", "OOM", "COUNT DISTINCT", "分区裁剪",
    ],
}


@dataclass(frozen=True)
class Skill:
    """A loaded skill with its name, content, and match keywords."""

    name: str
    filename: str
    content: str
    keywords: list[str] = field(default_factory=list)

    def matches(self, question: str) -> bool:
        q = question.lower()
        return any(kw.lower() in q for kw in self.keywords)

    def keyword_overlap(self, question: str) -> int:
        q = question.lower()
        return sum(1 for kw in self.keywords if kw.lower() in q)


def load_all_skills(skills_dir: str | Path | None = None) -> list[Skill]:
    """Load all skill markdown files from the skills directory."""
    directory = Path(skills_dir) if skills_dir else _DEFAULT_SKILLS_DIR
    if not directory.exists():
        return []

    skills: list[Skill] = []
    for md_file in sorted(directory.glob("*.md")):
        stem = md_file.stem
        content = md_file.read_text(encoding="utf-8")
        keywords = _SKILL_KEYWORDS.get(stem, _extract_keywords_from_content(content))
        skills.append(
            Skill(
                name=_extract_title(content) or stem,
                filename=md_file.name,
                content=content,
                keywords=keywords,
            )
        )
    return skills


def match_skill(
    question: str,
    skills: list[Skill],
    embedding_client: "EmbeddingClient | None" = None,
    similarity_threshold: float = 0.50,
) -> Skill | None:
    """Return the best-matching skill for the question, or None if no match.

    When *embedding_client* is provided the match is done via cosine similarity
    of question vs. skill-name + keywords embeddings (better recall for paraphrases).
    Without an embedding client the original keyword-overlap heuristic is used.
    """
    if not skills:
        return None
    if embedding_client is not None:
        return _match_by_embedding(question, skills, embedding_client, similarity_threshold)
    return _match_by_keywords(question, skills)


# ---------------------------------------------------------------------------
# SkillMatcher — stateful wrapper that caches skill embeddings
# ---------------------------------------------------------------------------

class SkillMatcher:
    """Matches questions to skills, caching skill embeddings across calls.

    Usage::

        matcher = SkillMatcher(skills, embedding_client=client)
        skill = matcher.match("肺癌患者本月药费统计")
    """

    def __init__(
        self,
        skills: list[Skill],
        embedding_client: "EmbeddingClient | None" = None,
        similarity_threshold: float = 0.50,
    ) -> None:
        self._skills = skills
        self._embedding_client = embedding_client
        self._threshold = similarity_threshold
        self._skill_embeddings: list[list[float]] | None = None

    def match(self, question: str) -> Skill | None:
        if self._embedding_client is None:
            return _match_by_keywords(question, self._skills)
        self._ensure_embeddings()
        q_vec = self._embedding_client.embed_texts([question])[0]
        best_score, best_skill = -1.0, None
        for skill, s_vec in zip(self._skills, self._skill_embeddings or []):  # type: ignore[arg-type]
            score = _cosine(q_vec, s_vec)
            if score > best_score:
                best_score, best_skill = score, skill
        if best_score >= self._threshold:
            return best_skill
        return None

    def _ensure_embeddings(self) -> None:
        if self._skill_embeddings is not None:
            return
        assert self._embedding_client is not None
        texts = [f"{s.name} {' '.join(s.keywords)}" for s in self._skills]
        self._skill_embeddings = self._embedding_client.embed_texts(texts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match_by_keywords(question: str, skills: list[Skill]) -> Skill | None:
    scored = [
        (skill.keyword_overlap(question), skill)
        for skill in skills
        if skill.matches(question)
    ]
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def _match_by_embedding(
    question: str,
    skills: list[Skill],
    client: "EmbeddingClient",
    threshold: float,
) -> Skill | None:
    skill_texts = [f"{s.name} {' '.join(s.keywords)}" for s in skills]
    all_vecs = client.embed_texts([question] + skill_texts)
    q_vec, skill_vecs = all_vecs[0], all_vecs[1:]
    best_score, best_skill = -1.0, None
    for skill, s_vec in zip(skills, skill_vecs):
        score = _cosine(q_vec, s_vec)
        if score > best_score:
            best_score, best_skill = score, skill
    if best_skill is not None and best_score >= threshold:
        return best_skill
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def inject_skill_into_prompt(system_prompt: str, skill: Skill) -> str:
    """Append the skill's content to the system prompt as a reference SOP."""
    skill_section = (
        f"\n\n## 参考技能：{skill.name}\n\n"
        f"以下是处理此类问题的标准流程和 SQL 模板，请严格遵循其中的业务口径和推荐表：\n\n"
        f"{skill.content}"
    )
    return system_prompt + skill_section


def _extract_title(content: str) -> str | None:
    """Extract the H1 title from markdown content."""
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_keywords_from_content(content: str) -> list[str]:
    """Fallback: extract keywords from the '触发关键词' line in the skill content."""
    for line in content.splitlines():
        if "触发关键词" in line:
            # Extract comma/colon separated words after the label
            parts = re.split(r"[：:，,、]", line)
            return [p.strip() for p in parts[1:] if p.strip()]
    return []
