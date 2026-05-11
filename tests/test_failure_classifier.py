"""Tests for failure classifier."""

from ai_data_agent.evaluation.failure_classifier import FailureCategory, FailureClassifier


def test_classify_missing_table():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={"tables_in_sql": False, "metrics_in_context": True},
        details={"tables_missing": ["dws.dws_tumor_drug_usage_1d"], "tables_found": []},
        error=None,
    )
    assert result.category == FailureCategory.MISSING_TABLE
    assert "dws.dws_tumor_drug_usage_1d" in result.detail


def test_classify_wrong_metric():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={"tables_in_sql": True, "metrics_in_context": False},
        details={"metrics_missing": ["drug_usage_amount"]},
        error=None,
    )
    assert result.category == FailureCategory.WRONG_METRIC
    assert "drug_usage_amount" in result.detail


def test_classify_wrong_dimension():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={"tables_in_sql": True, "metrics_in_context": True, "dimensions_in_sql": False},
        details={"dimensions_missing": ["dept_code"]},
        error=None,
    )
    assert result.category == FailureCategory.WRONG_DIMENSION


def test_classify_execution_error():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={},
        details={},
        error="Doris execution failed: table not found",
    )
    assert result.category == FailureCategory.EXECUTION_ERROR


def test_classify_timeout():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={},
        details={},
        error="Request timeout after 60s",
    )
    assert result.category == FailureCategory.TIMEOUT


def test_classify_retrieval_miss():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={},
        details={},
        error="Retrieval failed: Milvus connection refused",
    )
    assert result.category == FailureCategory.RETRIEVAL_MISS


def test_classify_guard_rejection():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={},
        details={},
        error="SQL generation rejected: SELECT * is not allowed",
    )
    assert result.category == FailureCategory.GUARD_REJECTION


def test_classify_pipeline_error():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={},
        details={},
        error="Something unexpected happened",
    )
    assert result.category == FailureCategory.PIPELINE_ERROR


def test_classify_unknown():
    classifier = FailureClassifier()
    result = classifier.classify(
        checks={"tables_in_sql": True, "metrics_in_context": True},
        details={},
        error=None,
    )
    assert result.category == FailureCategory.UNKNOWN
