from __future__ import annotations

from ai_data_agent.graphrag.context_builder import (
    DqRuleContext,
    MetricContext,
    RetrievedSource,
    TableContext,
    TextToSqlContext,
)
from ai_data_agent.text2sql.generator import SqlGenerationService, SqlGenerationError
from ai_data_agent.text2sql.llm import LlmClient
from ai_data_agent.text2sql.prompt_builder import build_text_to_sql_prompt
from ai_data_agent.text2sql.sql_guard import SqlGuardResult


class StubLlm(LlmClient):
    def __init__(self, response: str | list[str]):
        self.responses = response if isinstance(response, list) else [response]
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


class StubGuard:
    def __init__(self, result: SqlGuardResult):
        self.result = result
        self.sql_inputs: list[str] = []

    def validate(self, sql: str) -> SqlGuardResult:
        self.sql_inputs.append(sql)
        return self.result


class SequenceGuard:
    def __init__(self, results: list[SqlGuardResult]):
        self.results = results
        self.sql_inputs: list[str] = []

    def validate(self, sql: str) -> SqlGuardResult:
        self.sql_inputs.append(sql)
        return self.results.pop(0)


def _context() -> TextToSqlContext:
    return TextToSqlContext(
        question="统计本月肺癌患者抗肿瘤药物费用",
        sources=[
            RetrievedSource(
                doc_id="md-1",
                score=0.99,
                doc_type="metric",
                source_path="ai-data-agent/metadata/metric_catalog.yaml",
                table_name="dws.dws_tumor_drug_usage_1d",
                field_name="",
                metric_name="antitumor_drug_amount",
                content="抗肿瘤药物使用金额 = SUM(drug_amount)",
            )
        ],
        tables=[
            TableContext(
                name="dws.dws_tumor_drug_usage_1d",
                layer="DWS",
                domain="drug",
                description="肿瘤药物使用日汇总",
                key_fields=["stat_date", "drug_code"],
            )
        ],
        metrics=[
            MetricContext(
                name="antitumor_drug_amount",
                display_name="抗肿瘤药物使用金额",
                description="抗肿瘤药物医嘱或费用金额合计。",
                source_table="dws.dws_tumor_drug_usage_1d",
                formula="SUM(drug_amount)",
                time_field="stat_date",
                dimensions=["dept_code", "dept_name", "stat_month"],
                filters=["drug_category = 'ANTITUMOR'"],
            )
        ],
        dq_rules=[
            DqRuleContext(
                rule_code="DQ-011",
                name="药品编码非空检查",
                severity="HIGH",
                target_tables=["dwd.dwd_order"],
                target_fields=["drug_code"],
                fix_remark="核查 HIS 医嘱字典，补录药品编码。",
            )
        ],
        join_paths=[],
        lineages=[],
    )


def test_prompt_builder_includes_curated_context_sections() -> None:
    prompt = build_text_to_sql_prompt(_context())

    assert "统计本月肺癌患者抗肿瘤药物费用" in prompt
    assert "dws.dws_tumor_drug_usage_1d" in prompt
    assert "antitumor_drug_amount" in prompt
    assert "DQ-011" in prompt
    assert "只输出一条 Doris SELECT SQL" in prompt
    assert "优先输出名称字段" in prompt
    assert "dept_name" in prompt


def test_sql_generation_extracts_sql_from_markdown_and_validates_it() -> None:
    llm = StubLlm(
        """```sql
SELECT dept_code, SUM(drug_amount) AS antitumor_drug_amount
FROM dws.dws_tumor_drug_usage_1d
WHERE stat_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH)
LIMIT 100
```"""
    )
    guard = StubGuard(SqlGuardResult(allowed=True, tables=["dws.dws_tumor_drug_usage_1d"]))
    service = SqlGenerationService(llm, guard)

    result = service.generate(_context())

    assert result.sql.startswith("SELECT dept_code")
    assert guard.sql_inputs == [result.sql]
    assert result.guard_result.allowed is True
    assert "dws.dws_tumor_drug_usage_1d" in llm.prompts[0]


def test_sql_generation_rejects_sql_when_repair_still_fails() -> None:
    llm = StubLlm(
        [
            "DELETE FROM dws.dws_tumor_drug_usage_1d",
            "DELETE FROM dws.dws_tumor_drug_usage_1d",
        ]
    )
    guard = StubGuard(SqlGuardResult(allowed=False, reasons=["Only SELECT statements are allowed."]))
    service = SqlGenerationService(llm, guard)

    try:
        service.generate(_context())
    except SqlGenerationError as exc:
        assert "Only SELECT statements are allowed." in str(exc)
    else:
        raise AssertionError("Expected SQL generation to fail when guard rejects SQL")


def test_sql_generation_repairs_select_star_once() -> None:
    llm = StubLlm(
        [
            "SELECT * FROM dq.dq_issue_detail LIMIT 10",
            """
SELECT rule_code, drug_name, dept_code, dept_name, issue_reason
FROM dq.dq_issue_detail
LIMIT 10
""",
        ]
    )
    guard = SequenceGuard(
        [
            SqlGuardResult(allowed=False, reasons=["SELECT * is not allowed."]),
            SqlGuardResult(allowed=True, tables=["dq.dq_issue_detail"]),
        ]
    )
    service = SqlGenerationService(llm, guard)

    result = service.generate(_context())

    assert result.sql.startswith("SELECT rule_code")
    assert guard.sql_inputs == [
        "SELECT * FROM dq.dq_issue_detail LIMIT 10",
        result.sql,
    ]
    assert len(llm.prompts) == 2
    assert "你之前生成的 SQL 被安全校验拒绝" in llm.prompts[1]
