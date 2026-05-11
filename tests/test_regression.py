"""Tests for regression analyzer."""

from ai_data_agent.evaluation.regression import RegressionAnalyzer


def test_compare_detects_regression():
    analyzer = RegressionAnalyzer()
    baseline = {
        "pass_rate": 0.9,
        "results": [
            {"id": "q001", "domain": "drug", "passed": True},
            {"id": "q002", "domain": "drug", "passed": True},
        ],
    }
    current = {
        "pass_rate": 0.5,
        "results": [
            {"id": "q001", "domain": "drug", "passed": False, "checks": {"tables_in_sql": False}, "details": {}},
            {"id": "q002", "domain": "drug", "passed": True},
        ],
    }
    report = analyzer.compare(baseline, current)
    assert report.is_regression is True
    assert len(report.regressions) == 1
    assert report.regressions[0].question_id == "q001"
    assert report.delta < 0


def test_compare_detects_improvement():
    analyzer = RegressionAnalyzer()
    baseline = {
        "pass_rate": 0.5,
        "results": [
            {"id": "q001", "domain": "drug", "passed": False},
            {"id": "q002", "domain": "drug", "passed": True},
        ],
    }
    current = {
        "pass_rate": 1.0,
        "results": [
            {"id": "q001", "domain": "drug", "passed": True},
            {"id": "q002", "domain": "drug", "passed": True},
        ],
    }
    report = analyzer.compare(baseline, current)
    assert report.is_regression is False
    assert len(report.improvements) == 1
    assert report.improvements[0].question_id == "q001"
    assert report.delta > 0


def test_compare_no_change():
    analyzer = RegressionAnalyzer()
    data = {
        "pass_rate": 1.0,
        "results": [
            {"id": "q001", "domain": "drug", "passed": True},
        ],
    }
    report = analyzer.compare(data, data)
    assert report.is_regression is False
    assert len(report.regressions) == 0
    assert len(report.improvements) == 0
    assert report.delta == 0.0


def test_compare_failure_categories():
    analyzer = RegressionAnalyzer()
    baseline = {
        "pass_rate": 1.0,
        "results": [
            {"id": "q001", "domain": "drug", "passed": True},
            {"id": "q002", "domain": "tumor", "passed": True},
        ],
    }
    current = {
        "pass_rate": 0.0,
        "results": [
            {"id": "q001", "domain": "drug", "passed": False, "checks": {"tables_in_sql": False}, "details": {}},
            {"id": "q002", "domain": "tumor", "passed": False, "error": "Doris execution failed"},
        ],
    }
    report = analyzer.compare(baseline, current)
    assert report.is_regression is True
    assert "wrong_table" in report.new_failures_by_category
    assert "execution_error" in report.new_failures_by_category


def test_save_and_load_baseline(tmp_path):
    analyzer = RegressionAnalyzer()
    report = {"pass_rate": 0.8, "results": []}
    path = tmp_path / "baseline.json"
    analyzer.save_baseline(report, path)
    loaded = analyzer.load_baseline(path)
    assert loaded["pass_rate"] == 0.8
