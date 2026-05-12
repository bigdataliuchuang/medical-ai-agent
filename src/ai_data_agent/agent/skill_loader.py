"""Skill loading and matching: inject domain SOPs into the agent system prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

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


def match_skill(question: str, skills: list[Skill]) -> Skill | None:
    """Return the best-matching skill for the question, or None if no match."""
    scored = [
        (skill.keyword_overlap(question), skill)
        for skill in skills
        if skill.matches(question)
    ]
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


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
