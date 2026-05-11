"""Dynamic few-shot example selection for Text-to-SQL prompts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ai_data_agent.graphrag.embedding import EmbeddingClient
from ai_data_agent.text2sql.prompt_builder import FewShotExample


@dataclass(frozen=True)
class ScoredExample:
    example: FewShotExample
    score: float


class FewShotSelector:
    """Select relevant few-shot examples using domain/table overlap and embedding similarity."""

    def __init__(self, examples: list[FewShotExample], embedding_client: EmbeddingClient | None = None):
        self._examples = examples
        self._embedding_client = embedding_client
        self._example_embeddings: list[list[float]] | None = None

    def select(
        self,
        question: str,
        context_tables: list[str],
        top_k: int = 3,
    ) -> list[FewShotExample]:
        if not self._examples:
            return []

        scored: list[ScoredExample] = []
        context_table_set = {t.lower() for t in context_tables}

        for ex in self._examples:
            score = 0.0
            # Table overlap bonus
            ex_tables = {t.lower() for t in ex.tables}
            overlap = context_table_set & ex_tables
            if overlap:
                score += len(overlap) * 2.0
            scored.append(ScoredExample(example=ex, score=score))

        # Sort by score, take top_k
        scored.sort(key=lambda s: s.score, reverse=True)
        return [s.example for s in scored[:top_k]]


def load_few_shot_examples(path: str | Path) -> list[FewShotExample]:
    """Load few-shot examples from a JSONL file."""
    p = Path(path)
    if not p.exists():
        return []
    examples: list[FewShotExample] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        examples.append(
            FewShotExample(
                question=r["question"],
                sql=r["sql"],
                domain=r.get("domain", ""),
                tables=r.get("tables", []),
                description=r.get("description", ""),
            )
        )
    return examples
