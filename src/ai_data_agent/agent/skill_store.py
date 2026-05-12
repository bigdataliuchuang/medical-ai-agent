"""Skill accumulation layer: store and retrieve successful query patterns."""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_DB_PATH = "data/skill_store.db"
_SIMILARITY_THRESHOLD = 0.2
_DEDUP_THRESHOLD = 0.8


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    # Chinese characters are tokenized individually for fine-grained overlap scoring;
    # ASCII runs (column names, keywords) are kept as whole tokens.
    cjk = re.findall(r"[一-鿿]", text)
    latin = re.findall(r"[a-z0-9_]+", text)
    return set(cjk) | set(latin)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class SkillRecord:
    """A stored successful query pattern."""

    skill_id: str
    question: str
    sql: str
    tables_used: list[str]
    answer_summary: str
    success_count: int
    avg_latency_ms: float
    similarity: float = 0.0
    created_at: float = 0.0
    last_used: float = 0.0


class SkillStore:
    """SQLite-backed skill accumulation store.

    Saves successful agent executions and retrieves similar past patterns
    as few-shot context for future queries. Deduplicates near-identical
    questions by incrementing their success_count instead of inserting new rows.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id         TEXT PRIMARY KEY,
                    question         TEXT NOT NULL,
                    question_tokens  TEXT NOT NULL,
                    sql              TEXT NOT NULL,
                    tables_used      TEXT NOT NULL DEFAULT '[]',
                    answer_summary   TEXT NOT NULL DEFAULT '',
                    success_count    INTEGER NOT NULL DEFAULT 1,
                    total_latency_ms REAL NOT NULL DEFAULT 0,
                    created_at       REAL NOT NULL,
                    last_used        REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_skills_last_used ON skills(last_used)"
            )

    def save_skill(
        self,
        question: str,
        sql: str,
        tables_used: list[str] | None = None,
        answer_summary: str = "",
        latency_ms: float = 0.0,
    ) -> SkillRecord:
        """Persist a successful execution; dedup if a near-identical skill exists."""
        now = time.time()
        query_tokens = _tokenize(question)

        # Check for near-duplicate to avoid redundant rows
        existing = self.retrieve_similar(question, top_k=1)
        if existing and existing[0].similarity >= _DEDUP_THRESHOLD:
            old = existing[0]
            new_count = old.success_count + 1
            new_avg = (old.avg_latency_ms * old.success_count + latency_ms) / new_count
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE skills
                    SET success_count    = success_count + 1,
                        total_latency_ms = total_latency_ms + ?,
                        last_used        = ?
                    WHERE skill_id = ?
                    """,
                    (latency_ms, now, old.skill_id),
                )
            return SkillRecord(
                skill_id=old.skill_id,
                question=old.question,
                sql=sql,
                tables_used=tables_used or [],
                answer_summary=answer_summary,
                success_count=new_count,
                avg_latency_ms=new_avg,
                similarity=old.similarity,
                created_at=old.created_at,
                last_used=now,
            )

        skill_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills
                    (skill_id, question, question_tokens, sql, tables_used,
                     answer_summary, success_count, total_latency_ms, created_at, last_used)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    skill_id,
                    question,
                    json.dumps(list(query_tokens), ensure_ascii=False),
                    sql,
                    json.dumps(tables_used or [], ensure_ascii=False),
                    answer_summary,
                    latency_ms,
                    now,
                    now,
                ),
            )
        return SkillRecord(
            skill_id=skill_id,
            question=question,
            sql=sql,
            tables_used=tables_used or [],
            answer_summary=answer_summary,
            success_count=1,
            avg_latency_ms=latency_ms,
            similarity=1.0,
            created_at=now,
            last_used=now,
        )

    def retrieve_similar(self, question: str, top_k: int = 3) -> list[SkillRecord]:
        """Return up to top_k skills whose question tokens overlap with the query."""
        query_tokens = _tokenize(question)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT skill_id, question, question_tokens, sql, tables_used,
                       answer_summary, success_count, total_latency_ms, created_at, last_used
                FROM skills
                ORDER BY last_used DESC
                LIMIT 200
                """
            ).fetchall()

        scored: list[tuple[float, SkillRecord]] = []
        for row in rows:
            try:
                stored_tokens = set(json.loads(row["question_tokens"]))
            except (json.JSONDecodeError, TypeError):
                stored_tokens = set()
            sim = _jaccard(query_tokens, stored_tokens)
            if sim < _SIMILARITY_THRESHOLD:
                continue
            sc = row["success_count"]
            avg_lat = row["total_latency_ms"] / sc if sc > 0 else 0.0
            scored.append(
                (
                    sim,
                    SkillRecord(
                        skill_id=row["skill_id"],
                        question=row["question"],
                        sql=row["sql"],
                        tables_used=json.loads(row["tables_used"]) if row["tables_used"] else [],
                        answer_summary=row["answer_summary"],
                        success_count=sc,
                        avg_latency_ms=avg_lat,
                        similarity=sim,
                        created_at=row["created_at"],
                        last_used=row["last_used"],
                    ),
                )
            )

        scored.sort(key=lambda x: (-x[0], -x[1].success_count))
        return [r for _, r in scored[:top_k]]

    def get_stats(self) -> dict[str, object]:
        """Return aggregate statistics about the skill store."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total_skills,
                       COALESCE(SUM(success_count), 0) AS total_uses,
                       COALESCE(AVG(total_latency_ms / NULLIF(success_count, 0)), 0) AS avg_latency_ms
                FROM skills
                """
            ).fetchone()
        return {
            "total_skills": row["total_skills"],
            "total_uses": row["total_uses"],
            "avg_latency_ms": round(row["avg_latency_ms"], 1),
        }

    def prune_old_skills(
        self,
        min_success_count: int = 1,
        max_age_days: float = 90.0,
    ) -> int:
        """Delete skills not used recently and with low success counts."""
        cutoff = time.time() - max_age_days * 86400
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM skills WHERE last_used < ? AND success_count <= ?",
                (cutoff, min_success_count),
            )
            return cursor.rowcount
