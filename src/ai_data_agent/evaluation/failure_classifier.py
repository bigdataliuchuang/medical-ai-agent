"""Failure classification for evaluation results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    """Taxonomy of failure modes for Text-to-SQL evaluation."""

    WRONG_TABLE = "wrong_table"
    MISSING_TABLE = "missing_table"
    WRONG_METRIC = "wrong_metric"
    MISSING_FILTER = "missing_filter"
    WRONG_DIMENSION = "wrong_dimension"
    MISSING_LIMIT = "missing_limit"
    PARSE_ERROR = "parse_error"
    EXECUTION_ERROR = "execution_error"
    GUARD_REJECTION = "guard_rejection"
    SEMANTIC_ERROR = "semantic_error"
    RETRIEVAL_MISS = "retrieval_miss"
    TIMEOUT = "timeout"
    PIPELINE_ERROR = "pipeline_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    """Structured classification of a failed evaluation."""

    category: FailureCategory
    detail: str
    evidence: dict[str, Any]


class FailureClassifier:
    """Classify evaluation failures into structured categories."""

    def classify(
        self,
        checks: dict[str, bool],
        details: dict[str, Any],
        error: str | None,
    ) -> FailureClassification:
        # Pipeline error (e.g., retrieval or execution failure)
        if error:
            if "timeout" in error.lower():
                return FailureClassification(
                    category=FailureCategory.TIMEOUT,
                    detail=error,
                    evidence={"error": error},
                )
            if "retrieval" in error.lower():
                return FailureClassification(
                    category=FailureCategory.RETRIEVAL_MISS,
                    detail=error,
                    evidence={"error": error},
                )
            if "execution" in error.lower() or "doris" in error.lower():
                return FailureClassification(
                    category=FailureCategory.EXECUTION_ERROR,
                    detail=error,
                    evidence={"error": error},
                )
            if "guard" in error.lower() or "rejected" in error.lower():
                return FailureClassification(
                    category=FailureCategory.GUARD_REJECTION,
                    detail=error,
                    evidence={"error": error},
                )
            return FailureClassification(
                category=FailureCategory.PIPELINE_ERROR,
                detail=error,
                evidence={"error": error},
            )

        # Check-based classification
        if not checks.get("tables_in_sql", True):
            missing = details.get("tables_missing", [])
            found = details.get("tables_found", [])
            if found and not missing:
                category = FailureCategory.WRONG_TABLE
            else:
                category = FailureCategory.MISSING_TABLE
            return FailureClassification(
                category=category,
                detail=f"Missing tables: {missing}",
                evidence={"tables_missing": missing, "tables_found": found},
            )

        if not checks.get("metrics_in_context", True):
            missing = details.get("metrics_missing", [])
            return FailureClassification(
                category=FailureCategory.WRONG_METRIC,
                detail=f"Missing metrics in context: {missing}",
                evidence={"metrics_missing": missing},
            )

        if not checks.get("dimensions_in_sql", True):
            missing = details.get("dimensions_missing", [])
            return FailureClassification(
                category=FailureCategory.WRONG_DIMENSION,
                detail=f"Missing dimensions in SQL: {missing}",
                evidence={"dimensions_missing": missing},
            )

        if not checks.get("dq_rules_in_context", True):
            missing = details.get("dq_rules_missing", [])
            return FailureClassification(
                category=FailureCategory.MISSING_FILTER,
                detail=f"Missing DQ rules in context: {missing}",
                evidence={"dq_rules_missing": missing},
            )

        if not checks.get("fields_in_sql", True):
            missing = details.get("fields_missing", [])
            return FailureClassification(
                category=FailureCategory.MISSING_FILTER,
                detail=f"Missing fields in SQL: {missing}",
                evidence={"fields_missing": missing},
            )

        return FailureClassification(
            category=FailureCategory.UNKNOWN,
            detail="No specific failure category matched",
            evidence={"checks": checks},
        )
