from __future__ import annotations

from ai_data_agent.agent.audit import AuditLogger, AuditRecord
from ai_data_agent.agent.result_analyzer import ResultAnalyzer
from ai_data_agent.executor.doris import DorisQueryResult
from ai_data_agent.graphrag.context_builder import TextToSqlContext


class StubLlm:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "本月抗肿瘤药物费用最高的科室是肿瘤内科。建议按药品、医生、患者继续下钻。"


class RecordingAuditLogger(AuditLogger):
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)


def test_result_analyzer_uses_query_result_and_returns_suggestions() -> None:
    llm = StubLlm()
    analyzer = ResultAnalyzer(llm)
    result = DorisQueryResult(
        columns=["dept_name", "amount"],
        rows=[{"dept_name": "肿瘤内科", "amount": 120000}],
        row_count=1,
        elapsed_ms=25,
    )

    analysis = analyzer.analyze(
        question="本月抗肿瘤药物费用异常增长的科室有哪些？",
        sql="SELECT dept_name, amount FROM ads.ads_drug_usage_trend LIMIT 100",
        query_result=result,
        context=TextToSqlContext(
            question="本月抗肿瘤药物费用异常增长的科室有哪些？",
            sources=[],
            tables=[],
            metrics=[],
            dq_rules=[],
            join_paths=[],
            lineages=[],
        ),
    )

    assert "肿瘤内科" in analysis.answer
    assert "按药品下钻" in analysis.downstream_suggestions
    assert "dept_name" in llm.prompts[0]


def test_audit_logger_contract_records_full_query_lifecycle() -> None:
    logger = RecordingAuditLogger()
    record = AuditRecord(
        request_id="req-1",
        question="test question",
        sql="SELECT 1 LIMIT 1",
        status="success",
        retrieved_sources=2,
        context_tables=["dws.t1"],
        context_metrics=["m1"],
        context_dq_rules=["DQ-001"],
        row_count=1,
        elapsed_ms=10,
        error_message=None,
        answer_summary="ok",
    )

    logger.write(record)

    assert logger.records == [record]
    assert logger.records[0].request_id == "req-1"
