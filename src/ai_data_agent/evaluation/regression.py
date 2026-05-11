"""Regression analysis for evaluation reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RegressionItem:
    """A single regression or improvement."""

    question_id: str
    domain: str
    baseline_status: str
    current_status: str
    failure_category: str | None = None


@dataclass(frozen=True)
class RegressionReport:
    """Comparison between baseline and current evaluation runs."""

    baseline_path: str
    current_pass_rate: float
    baseline_pass_rate: float
    delta: float
    regressions: list[RegressionItem]
    improvements: list[RegressionItem]
    new_failures_by_category: dict[str, int]
    is_regression: bool


class RegressionAnalyzer:
    """Compare evaluation runs to detect regressions."""

    def compare(
        self,
        baseline: dict[str, Any],
        current: dict[str, Any],
    ) -> RegressionReport:
        baseline_results = {r["id"]: r for r in baseline.get("results", [])}
        current_results = {r["id"]: r for r in current.get("results", [])}

        regressions: list[RegressionItem] = []
        improvements: list[RegressionItem] = []
        new_failures_by_category: dict[str, int] = {}

        for qid in set(baseline_results.keys()) | set(current_results.keys()):
            base = baseline_results.get(qid)
            curr = current_results.get(qid)

            if base is None or curr is None:
                continue

            base_passed = base.get("passed", False)
            curr_passed = curr.get("passed", False)

            if base_passed and not curr_passed:
                # Regression
                category = self._extract_failure_category(curr)
                regressions.append(
                    RegressionItem(
                        question_id=qid,
                        domain=curr.get("domain", ""),
                        baseline_status="passed",
                        current_status="failed",
                        failure_category=category,
                    )
                )
                new_failures_by_category[category] = new_failures_by_category.get(category, 0) + 1

            elif not base_passed and curr_passed:
                # Improvement
                improvements.append(
                    RegressionItem(
                        question_id=qid,
                        domain=curr.get("domain", ""),
                        baseline_status="failed",
                        current_status="passed",
                    )
                )

        baseline_rate = baseline.get("pass_rate", 0.0)
        current_rate = current.get("pass_rate", 0.0)

        return RegressionReport(
            baseline_path="",
            current_pass_rate=current_rate,
            baseline_pass_rate=baseline_rate,
            delta=current_rate - baseline_rate,
            regressions=regressions,
            improvements=improvements,
            new_failures_by_category=new_failures_by_category,
            is_regression=len(regressions) > 0,
        )

    def load_baseline(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def save_baseline(self, report: dict[str, Any], path: Path) -> None:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_failure_category(result: dict[str, Any]) -> str:
        error = result.get("error")
        if error:
            if "timeout" in error.lower():
                return "timeout"
            if "retrieval" in error.lower():
                return "retrieval_miss"
            if "execution" in error.lower():
                return "execution_error"
            return "pipeline_error"

        checks = result.get("checks", {})
        if not checks.get("tables_in_sql", True):
            return "wrong_table"
        if not checks.get("metrics_in_context", True):
            return "wrong_metric"
        if not checks.get("dimensions_in_sql", True):
            return "wrong_dimension"
        if not checks.get("dq_rules_in_context", True):
            return "missing_filter"
        return "unknown"
