"""Evaluation Harness: assess agent SQL generation quality against benchmark questions."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

_DEFAULT_QUESTIONS_PATH = Path(__file__).parent / "benchmark_questions.yaml"
_DEFAULT_REPORT_PATH = Path(__file__).parent / "eval_report.md"

# Schemas the SQL guard is configured with for evaluation
_EVAL_ALLOWED_SCHEMAS = ["ads", "dws", "dwd", "dim", "dq", "ods"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkQuestion:
    id: str
    domain: str
    difficulty: str
    question: str
    expected_tables: list[str]
    expected_metrics: list[str] = field(default_factory=list)
    expected_fields: list[str] = field(default_factory=list)


@dataclass
class QuestionResult:
    question_id: str
    question: str
    domain: str
    difficulty: str
    generated_sql: str
    actual_tables: list[str]
    expected_tables: list[str]
    sql_valid: bool
    sql_safe: bool
    table_jaccard: float
    elapsed_ms: int
    error: str | None = None


@dataclass
class EvalSummary:
    total: int
    sql_valid_rate: float
    sql_safe_rate: float
    table_match_rate: float  # avg Jaccard across all questions
    avg_elapsed_ms: float
    by_domain: dict[str, dict[str, float]] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class EvalReport:
    eval_run_id: str
    question_results: list[QuestionResult]
    summary: EvalSummary

    def to_json(self) -> dict:
        return {
            "eval_run_id": self.eval_run_id,
            "summary": {
                "total": self.summary.total,
                "sql_valid_rate": self.summary.sql_valid_rate,
                "sql_safe_rate": self.summary.sql_safe_rate,
                "table_match_rate": self.summary.table_match_rate,
                "avg_elapsed_ms": self.summary.avg_elapsed_ms,
            },
            "by_domain": self.summary.by_domain,
            "by_difficulty": self.summary.by_difficulty,
            "results": [
                {
                    "id": r.question_id,
                    "domain": r.domain,
                    "difficulty": r.difficulty,
                    "question": r.question,
                    "generated_sql": r.generated_sql,
                    "actual_tables": r.actual_tables,
                    "expected_tables": r.expected_tables,
                    "sql_valid": r.sql_valid,
                    "sql_safe": r.sql_safe,
                    "table_jaccard": r.table_jaccard,
                    "elapsed_ms": r.elapsed_ms,
                    "error": r.error,
                }
                for r in self.question_results
            ],
        }

    def to_markdown(self) -> str:
        s = self.summary
        lines = [
            f"# Evaluation Report — {self.eval_run_id}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total questions | {s.total} |",
            f"| SQL valid rate | {s.sql_valid_rate:.1%} |",
            f"| SQL safe rate | {s.sql_safe_rate:.1%} |",
            f"| Table match rate (avg Jaccard) | {s.table_match_rate:.1%} |",
            f"| Avg latency | {s.avg_elapsed_ms:.0f} ms |",
            "",
            "## Results by Domain",
            "",
            "| Domain | Questions | Valid% | Safe% | Table Match% |",
            "|--------|-----------|--------|-------|--------------|",
        ]
        for domain, metrics in sorted(s.by_domain.items()):
            lines.append(
                f"| {domain} | {metrics.get('count', 0):.0f} "
                f"| {metrics.get('valid', 0):.1%} "
                f"| {metrics.get('safe', 0):.1%} "
                f"| {metrics.get('table_match', 0):.1%} |"
            )
        lines += [
            "",
            "## Results by Difficulty",
            "",
            "| Difficulty | Questions | Valid% | Safe% | Table Match% |",
            "|------------|-----------|--------|-------|--------------|",
        ]
        for diff, metrics in sorted(s.by_difficulty.items()):
            lines.append(
                f"| {diff} | {metrics.get('count', 0):.0f} "
                f"| {metrics.get('valid', 0):.1%} "
                f"| {metrics.get('safe', 0):.1%} "
                f"| {metrics.get('table_match', 0):.1%} |"
            )
        lines += [
            "",
            "## Question Details",
            "",
            "| ID | Domain | Difficulty | Valid | Safe | Table Match | Elapsed |",
            "|----|--------|------------|-------|------|-------------|---------|",
        ]
        for r in self.question_results:
            v = "✓" if r.sql_valid else "✗"
            s_mark = "✓" if r.sql_safe else "✗"
            lines.append(
                f"| {r.question_id} | {r.domain} | {r.difficulty} "
                f"| {v} | {s_mark} | {r.table_jaccard:.2f} | {r.elapsed_ms}ms |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EvalRunner:
    """Run benchmark questions against an agent function and produce an EvalReport.

    The agent_fn receives a question string and returns a dict with key "sql"
    (or an empty string if no SQL was generated). This design keeps the runner
    decoupled from the actual agent implementation.

    Example usage::

        def my_agent(question: str) -> dict:
            return {"sql": generate_sql(question)}

        runner = EvalRunner()
        report = runner.run(runner.load_questions(), my_agent)
        print(report.to_markdown())
    """

    def __init__(
        self,
        questions_path: str | Path | None = None,
        allowed_schemas: list[str] | None = None,
    ) -> None:
        self._questions_path = Path(questions_path or _DEFAULT_QUESTIONS_PATH)
        self._allowed_schemas = allowed_schemas or _EVAL_ALLOWED_SCHEMAS

    def load_questions(self) -> list[BenchmarkQuestion]:
        with open(self._questions_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return [
            BenchmarkQuestion(
                id=q["id"],
                domain=q["domain"],
                difficulty=q.get("difficulty", "medium"),
                question=q["question"],
                expected_tables=q.get("expected_tables", []),
                expected_metrics=q.get("expected_metrics", []),
                expected_fields=q.get("expected_fields", []),
            )
            for q in data.get("questions", [])
        ]

    def run(
        self,
        questions: list[BenchmarkQuestion],
        agent_fn: Callable[[str], dict],
        eval_run_id: str | None = None,
    ) -> EvalReport:
        eval_run_id = eval_run_id or uuid.uuid4().hex[:12]
        results: list[QuestionResult] = []

        for q in questions:
            result = self._evaluate_one(q, agent_fn)
            results.append(result)

        summary = _compute_summary(results)
        return EvalReport(
            eval_run_id=eval_run_id,
            question_results=results,
            summary=summary,
        )

    def _evaluate_one(
        self,
        question: BenchmarkQuestion,
        agent_fn: Callable[[str], dict],
    ) -> QuestionResult:
        t0 = time.monotonic()
        sql = ""
        error = None
        try:
            output = agent_fn(question.question)
            sql = output.get("sql", "") or ""
        except Exception as exc:
            error = str(exc)
        elapsed = int((time.monotonic() - t0) * 1000)

        sql_valid = _is_sql_valid(sql)
        sql_safe, actual_tables = _check_sql_safety(sql, self._allowed_schemas)
        table_jaccard = _jaccard(
            set(_normalise_tables(question.expected_tables)),
            set(_normalise_tables(actual_tables)),
        )

        return QuestionResult(
            question_id=question.id,
            question=question.question,
            domain=question.domain,
            difficulty=question.difficulty,
            generated_sql=sql,
            actual_tables=actual_tables,
            expected_tables=question.expected_tables,
            sql_valid=sql_valid,
            sql_safe=sql_safe,
            table_jaccard=table_jaccard,
            elapsed_ms=elapsed,
            error=error,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_sql_valid(sql: str) -> bool:
    if not sql.strip():
        return False
    try:
        import sqlglot
        parsed = sqlglot.parse(sql.strip(), read="mysql")
        return len(parsed) == 1 and parsed[0] is not None
    except Exception:
        return False


def _check_sql_safety(sql: str, allowed_schemas: list[str]) -> tuple[bool, list[str]]:
    if not sql.strip():
        return False, []
    try:
        from ai_data_agent.text2sql.sql_guard import SqlGuard
        guard = SqlGuard(
            allowed_schemas=allowed_schemas,
            deny_select_star=True,
            require_limit_for_detail_query=True,
            require_time_filter=False,
            block_sensitive_fields=True,
        )
        result = guard.validate(sql)
        return result.allowed, result.tables
    except Exception:
        return False, []


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalise_tables(tables: list[str]) -> list[str]:
    return [t.lower().strip() for t in tables]


def _compute_summary(results: list[QuestionResult]) -> EvalSummary:
    total = len(results)
    if total == 0:
        return EvalSummary(0, 0.0, 0.0, 0.0, 0.0)

    valid_cnt = sum(1 for r in results if r.sql_valid)
    safe_cnt = sum(1 for r in results if r.sql_safe)
    avg_jaccard = sum(r.table_jaccard for r in results) / total
    avg_elapsed = sum(r.elapsed_ms for r in results) / total

    def _group_metrics(key_fn: Callable) -> dict[str, dict[str, float]]:
        groups: dict[str, list[QuestionResult]] = {}
        for r in results:
            groups.setdefault(key_fn(r), []).append(r)
        out: dict[str, dict[str, float]] = {}
        for k, items in groups.items():
            n = len(items)
            out[k] = {
                "count": n,
                "valid": sum(1 for i in items if i.sql_valid) / n,
                "safe": sum(1 for i in items if i.sql_safe) / n,
                "table_match": sum(i.table_jaccard for i in items) / n,
            }
        return out

    return EvalSummary(
        total=total,
        sql_valid_rate=valid_cnt / total,
        sql_safe_rate=safe_cnt / total,
        table_match_rate=avg_jaccard,
        avg_elapsed_ms=avg_elapsed,
        by_domain=_group_metrics(lambda r: r.domain),
        by_difficulty=_group_metrics(lambda r: r.difficulty),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    def _stub_agent(question: str) -> dict:
        """Stub agent that returns a dummy SQL — replace with real agent call."""
        return {
            "sql": (
                "SELECT COUNT(DISTINCT mpi_id) AS cnt "
                "FROM dwd.dwd_visit "
                "WHERE stat_date >= '2025-01-01' "
                "LIMIT 1"
            )
        }

    runner = EvalRunner()
    questions = runner.load_questions()
    print(f"Loaded {len(questions)} benchmark questions.")

    report = runner.run(questions, _stub_agent)
    md = report.to_markdown()

    report_path = _DEFAULT_REPORT_PATH
    report_path.write_text(md, encoding="utf-8")
    print(f"Report written to {report_path}")
    print(f"\nSummary: valid={report.summary.sql_valid_rate:.1%}  "
          f"safe={report.summary.sql_safe_rate:.1%}  "
          f"table_match={report.summary.table_match_rate:.1%}")
