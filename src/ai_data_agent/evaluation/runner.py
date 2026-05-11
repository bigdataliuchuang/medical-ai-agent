"""Batch evaluation runner for the Data Agent query pipeline."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_data_agent.evaluation.failure_classifier import FailureClassification, FailureClassifier


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    domain: str
    question: str
    expected_tables: list[str] = field(default_factory=list)
    expected_metrics: list[str] = field(default_factory=list)
    expected_dimensions: list[str] = field(default_factory=list)
    expected_filters: list[str] = field(default_factory=list)
    expected_dq_rules: list[str] = field(default_factory=list)
    expected_fields: list[str] = field(default_factory=list)
    expected_row_count_min: int | None = None
    expected_row_count_max: int | None = None
    expected_column_hints: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    question_id: str
    domain: str
    question: str
    passed: bool
    sql: str
    checks: dict[str, bool]
    details: dict[str, Any]
    elapsed_ms: int
    error: str | None = None
    execution_success: bool | None = None
    actual_row_count: int | None = None
    actual_columns: list[str] = field(default_factory=list)
    failure_classification: FailureClassification | None = None


def load_questions(path: str | Path) -> list[EvalQuestion]:
    records = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [
        EvalQuestion(
            id=r["id"],
            domain=r["domain"],
            question=r["question"],
            expected_tables=r.get("expected_tables", []),
            expected_metrics=r.get("expected_metrics", []),
            expected_dimensions=r.get("expected_dimensions", []),
            expected_filters=r.get("expected_filters", []),
            expected_dq_rules=r.get("expected_dq_rules", []),
            expected_fields=r.get("expected_fields", []),
        )
        for r in records
    ]


def evaluate_question(
    question: EvalQuestion,
    sql: str,
    context_tables: list[str],
    context_metrics: list[str],
    context_dq_rules: list[str],
    elapsed_ms: int,
    error: str | None = None,
) -> EvalResult:
    checks: dict[str, bool] = {}

    if error:
        return EvalResult(
            question_id=question.id,
            domain=question.domain,
            question=question.question,
            passed=False,
            sql=sql,
            checks={"pipeline_error": False},
            details={"error": error},
            elapsed_ms=elapsed_ms,
            error=error,
        )

    sql_lower = sql.lower()

    # Check: expected tables referenced in generated SQL
    if question.expected_tables:
        tables_found = []
        tables_missing = []
        for table in question.expected_tables:
            table_pattern = table.lower().replace(".", r"\s*\.\s*")
            if re.search(table_pattern, sql_lower):
                tables_found.append(table)
            else:
                tables_missing.append(table)
        checks["tables_in_sql"] = len(tables_missing) == 0
    else:
        tables_found = []
        tables_missing = []

    # Check: expected metrics surfaced in context
    if question.expected_metrics:
        metrics_found = [m for m in question.expected_metrics if m in context_metrics]
        metrics_missing = [m for m in question.expected_metrics if m not in context_metrics]
        checks["metrics_in_context"] = len(metrics_missing) == 0
    else:
        metrics_found = []
        metrics_missing = []

    # Check: expected DQ rules in context
    if question.expected_dq_rules:
        dq_found = [r for r in question.expected_dq_rules if r in context_dq_rules]
        dq_missing = [r for r in question.expected_dq_rules if r not in context_dq_rules]
        checks["dq_rules_in_context"] = len(dq_missing) == 0
    else:
        dq_found = []
        dq_missing = []

    # Check: expected dimensions appear in SQL SELECT or GROUP BY
    if question.expected_dimensions:
        dims_found = [d for d in question.expected_dimensions if d.lower() in sql_lower]
        dims_missing = [d for d in question.expected_dimensions if d.lower() not in sql_lower]
        checks["dimensions_in_sql"] = len(dims_missing) == 0
    else:
        dims_found = []
        dims_missing = []

    # Check: expected fields in context tables
    if question.expected_fields:
        fields_found = [f for f in question.expected_fields if f.lower() in sql_lower]
        fields_missing = [f for f in question.expected_fields if f.lower() not in sql_lower]
        checks["fields_in_sql"] = len(fields_missing) == 0
    else:
        fields_found = []
        fields_missing = []

    # Check: expected filters in SQL WHERE clause
    if question.expected_filters:
        filters_found = [f for f in question.expected_filters if f.lower() in sql_lower]
        filters_missing = [f for f in question.expected_filters if f.lower() not in sql_lower]
        checks["filters_in_sql"] = len(filters_missing) == 0
    else:
        filters_found = []
        filters_missing = []

    passed = all(checks.values()) if checks else True

    details = {
        "tables_found": tables_found,
        "tables_missing": tables_missing,
        "metrics_found": metrics_found,
        "metrics_missing": metrics_missing,
        "dq_rules_found": dq_found,
        "dq_rules_missing": dq_missing,
        "dimensions_found": dims_found,
        "dimensions_missing": dims_missing,
        "fields_found": fields_found,
        "fields_missing": fields_missing,
        "filters_found": filters_found,
        "filters_missing": filters_missing,
    }

    # Classify failure if not passed
    failure_classification = None
    if not passed:
        classifier = FailureClassifier()
        failure_classification = classifier.classify(checks, details, None)

    return EvalResult(
        question_id=question.id,
        domain=question.domain,
        question=question.question,
        passed=passed,
        sql=sql,
        checks=checks,
        details=details,
        elapsed_ms=elapsed_ms,
        failure_classification=failure_classification,
    )


@dataclass
class EvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    results: list[EvalResult]
    domain_summary: dict[str, dict[str, int]]
    total_elapsed_ms: int
    failure_summary: dict[str, int] = field(default_factory=dict)
    avg_elapsed_ms: float = 0.0
    p50_elapsed_ms: float = 0.0
    p95_elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "total_elapsed_ms": self.total_elapsed_ms,
            "avg_elapsed_ms": round(self.avg_elapsed_ms, 1),
            "p50_elapsed_ms": round(self.p50_elapsed_ms, 1),
            "p95_elapsed_ms": round(self.p95_elapsed_ms, 1),
            "domain_summary": self.domain_summary,
            "failure_summary": self.failure_summary,
            "results": [
                {
                    "id": r.question_id,
                    "domain": r.domain,
                    "question": r.question,
                    "passed": r.passed,
                    "sql": r.sql,
                    "checks": r.checks,
                    "details": r.details,
                    "elapsed_ms": r.elapsed_ms,
                    "error": r.error,
                    "failure_category": r.failure_classification.category.value if r.failure_classification else None,
                }
                for r in self.results
            ],
        }

    def summary_table(self) -> str:
        lines = [
            f"{'ID':<6} {'Domain':<10} {'Pass':<6} {'Checks'}",
            "-" * 70,
        ]
        for r in self.results:
            checks_str = ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in r.checks.items())
            lines.append(f"{r.question_id:<6} {r.domain:<10} {'✓' if r.passed else '✗':<6} {checks_str}")
        lines.append("-" * 70)
        lines.append(f"Total: {self.total}  Passed: {self.passed}  Failed: {self.failed}  Rate: {self.pass_rate:.1%}")
        lines.append(f"Timing: avg={self.avg_elapsed_ms:.0f}ms  p50={self.p50_elapsed_ms:.0f}ms  p95={self.p95_elapsed_ms:.0f}ms")
        if self.failure_summary:
            lines.append(f"Failure categories: {json.dumps(self.failure_summary, ensure_ascii=False)}")
        lines.append(f"Domains: {json.dumps(self.domain_summary, ensure_ascii=False)}")
        return "\n".join(lines)


def build_report(results: list[EvalResult]) -> EvalReport:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pass_rate = passed / total if total else 0.0

    domain_summary: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = domain_summary.setdefault(r.domain, {"passed": 0, "failed": 0})
        if r.passed:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

    # Failure category summary
    failure_summary: dict[str, int] = {}
    for r in results:
        if r.failure_classification:
            cat = r.failure_classification.category.value
            failure_summary[cat] = failure_summary.get(cat, 0) + 1

    # Timing statistics
    elapsed_times = sorted(r.elapsed_ms for r in results)
    total_elapsed = sum(elapsed_times)
    avg_elapsed = total_elapsed / total if total else 0.0
    p50 = _percentile(elapsed_times, 50) if elapsed_times else 0.0
    p95 = _percentile(elapsed_times, 95) if elapsed_times else 0.0

    return EvalReport(
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=pass_rate,
        results=results,
        domain_summary=domain_summary,
        total_elapsed_ms=total_elapsed,
        failure_summary=failure_summary,
        avg_elapsed_ms=avg_elapsed,
        p50_elapsed_ms=p50,
        p95_elapsed_ms=p95,
    )


def _percentile(sorted_values: list[int], pct: int) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return float(sorted_values[-1])
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
