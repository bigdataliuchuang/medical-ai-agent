import os
import re
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
METADATA_DIR = os.path.join(ROOT_DIR, "metadata")


def _load_yaml(name: str) -> dict[str, Any]:
    path = os.path.join(METADATA_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fp:
        loaded = yaml.safe_load(fp) or {}
    return loaded if isinstance(loaded, dict) else {}


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-zA-Z0-9_]+", lowered))
    chinese_terms = {
        term
        for term in [
            "抗肿瘤", "药物", "用药", "费用", "患者", "住院", "重复", "审核",
            "主数据", "质量", "dq", "mpi", "肺癌", "检验", "异常",
        ]
        if term in lowered
    }
    return words | chinese_terms


def _metric_score(requirement: str, metric: dict[str, Any]) -> int:
    haystack = " ".join(
        str(metric.get(key, ""))
        for key in ["name", "display_name", "description", "source_table", "formula"]
    )
    score = len(_tokens(requirement) & _tokens(haystack))
    if metric.get("display_name") and str(metric["display_name"]) in requirement:
        score += 3
    return score


def _pick_metric(requirement: str, catalog: dict[str, Any]) -> dict[str, Any] | None:
    metrics = catalog.get("metrics") or []
    if not isinstance(metrics, list):
        return None
    ranked = sorted(metrics, key=lambda item: _metric_score(requirement, item), reverse=True)
    if not ranked or _metric_score(requirement, ranked[0]) == 0:
        return None
    return ranked[0]


def _builtin_metric(requirement: str) -> dict[str, Any] | None:
    text = requirement.lower()
    if "抗肿瘤" in text or "用药" in text or "药物" in text:
        return {
            "name": "antitumor_drug_usage_intensity",
            "display_name": "抗肿瘤药物使用强度",
            "description": "按日期、科室和药品统计抗肿瘤药物使用患者数、金额和使用强度。",
            "source_table": "dws.dws_tumor_drug_usage_1d",
            "formula": "SUM(drug_amount)",
            "time_field": "stat_date",
            "dimensions": ["stat_date", "dept_code", "dept_name", "drug_name"],
            "filters": ["drug_category = 'ANTITUMOR'"],
        }
    if "重复" in text or "审核" in text or "mpi" in text or "主数据" in text:
        return {
            "name": "mpi_pending_review_cnt",
            "display_name": "MPI 待审核重复患者数",
            "description": "统计患者主索引中待人工审核的疑似重复患者队列长度。",
            "source_table": "ads.ads_patient_mpi_summary",
            "formula": "SUM(pending_review_cnt)",
            "time_field": "stat_date",
            "dimensions": ["stat_date"],
            "filters": [],
        }
    return None


def _domain_from_requirement(requirement: str, metric: dict[str, Any] | None, domain: str | None) -> str:
    if domain:
        return domain
    text = requirement.lower()
    if "dq" in text or "质量" in text:
        return "数据质量"
    if "mpi" in text or "重复" in text or "主数据" in text or "患者" in text:
        return "患者主数据"
    if "药" in text or "抗肿瘤" in text or "用药" in text:
        return "药物监测"
    if "费用" in text:
        return "费用分析"
    if "住院" in text:
        return "住院质量"
    if metric:
        return str(metric.get("display_name", "医疗数据治理")).split("指标")[0]
    return "医疗数据治理"


def _source_tables(metric: dict[str, Any] | None, schema_catalog: dict[str, Any]) -> list[str]:
    if metric and metric.get("source_table"):
        return [str(metric["source_table"])]
    schemas = schema_catalog.get("tables") or schema_catalog.get("schemas") or []
    tables: list[str] = []
    if isinstance(schemas, list):
        for item in schemas[:4]:
            if isinstance(item, dict):
                name = item.get("full_name") or item.get("table_name") or item.get("name")
                if name:
                    tables.append(str(name))
    return tables or ["dwd.dwd_visit", "dwd.dwd_order", "dim.dim_drug"]


def _metric_code(requirement: str, metric: dict[str, Any] | None) -> str:
    if metric and metric.get("name"):
        return str(metric["name"])
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", requirement.lower()).strip("_")
    return slug[:48] or "new_medical_metric"


def _sql_draft(metric_code: str, source_table: str, metric: dict[str, Any] | None) -> str:
    time_field = str(metric.get("time_field", "stat_date")) if metric else "stat_date"
    formula = str(metric.get("formula", "COUNT(1)")) if metric else "COUNT(1)"
    dimensions = metric.get("dimensions", ["stat_date"]) if metric else ["stat_date"]
    if not isinstance(dimensions, list) or not dimensions:
        dimensions = ["stat_date"]
    dim_cols = [str(col) for col in dimensions[:4]]
    select_cols = ",\n    ".join(dim_cols)
    group_cols = ", ".join(dim_cols)
    filters = metric.get("filters", []) if metric else []
    where_parts = [f"{time_field} >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"]
    if isinstance(filters, list):
        where_parts.extend(str(item) for item in filters[:3])
    where_sql = "\n  AND ".join(where_parts)
    return (
        f"-- ADS draft for {metric_code}\n"
        f"SELECT\n"
        f"    {select_cols},\n"
        f"    {formula} AS {metric_code}\n"
        f"FROM {source_table}\n"
        f"WHERE {where_sql}\n"
        f"GROUP BY {group_cols}\n"
        f"LIMIT 100;"
    )


def _unique(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item)
        if value not in result:
            result.append(value)
    return result


def _markdown_for_plan(plan: dict[str, Any]) -> str:
    dq_lines = [
        f"- `{rule['rule_code']}` [{rule['severity']}]: {rule['rule_name']}"
        for rule in plan.get("dq_rules", [])
    ]
    forbidden = [f"- {item}" for item in plan.get("drilldown_policy", {}).get("forbidden", [])]
    return "\n".join(
        [
            f"# {plan['metric_name']}",
            "",
            f"- 指标编码：`{plan['metric_code']}`",
            f"- 业务域：{plan['business_domain']}",
            f"- 推荐源表：{', '.join(plan.get('source_tables', []))}",
            f"- DWS 表：`{plan['dws_design']['table_name']}`",
            f"- ADS 表：`{plan['ads_design']['table_name']}`",
            "",
            "## SQL 草稿",
            "",
            "```sql",
            plan.get("sql_draft", ""),
            "```",
            "",
            "## DQ 规则",
            "",
            *(dq_lines or ["- 暂无"]),
            "",
            "## 安全下钻限制",
            "",
            *(forbidden or ["- 暂无"]),
            "",
        ]
    )


def save_metric_asset(plan: dict[str, Any], output_dir: str | Path | None = None) -> dict[str, str]:
    metric_code = str(plan["metric_code"])
    target_dir = Path(output_dir) if output_dir is not None else Path(ROOT_DIR) / "semantic_layer" / "generated"
    target_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = target_dir / f"{metric_code}.yaml"
    markdown_path = target_dir / f"{metric_code}.md"
    yaml_path.write_text(
        yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_for_plan(plan), encoding="utf-8")
    return {
        "metric_code": metric_code,
        "yaml_path": str(yaml_path),
        "markdown_path": str(markdown_path),
    }


def build_metric_plan(requirement: str, domain: str | None = None) -> dict[str, Any]:
    metric_catalog = _load_yaml("metric_catalog.yaml")
    schema_catalog = _load_yaml("schema_catalog.yaml")
    lineage_graph = _load_yaml("lineage_graph.yaml")
    metric = _builtin_metric(requirement) or _pick_metric(requirement, metric_catalog)
    metric_code = _metric_code(requirement, metric)
    business_domain = _domain_from_requirement(requirement, metric, domain)
    sources = _source_tables(metric, schema_catalog)
    source_table = sources[0]
    display_name = str(metric.get("display_name", requirement)) if metric else requirement
    formula = str(metric.get("formula", "需要结合业务口径确认计算公式")) if metric else "需要结合业务口径确认计算公式"

    warnings = []
    if metric is None:
        warnings.append("未命中现有指标目录，以下方案是基于通用医疗数仓模式生成的草案，需要数开确认口径。")
    warnings.append("MVP 只生成 SQL 草稿，不直接执行 DWD/ODS 明细查询。")

    dws_grain = _unique(["stat_date"] + (metric.get("dimensions", [])[:3] if metric else ["dept_code", "dept_name"]))

    return {
        "requirement": requirement,
        "metric_code": metric_code,
        "metric_name": display_name,
        "business_domain": business_domain,
        "source_tables": sources,
        "dws_design": {
            "table_name": f"dws.dws_{metric_code}_1d",
            "grain": dws_grain,
            "measures": [formula],
            "description": f"按日沉淀「{display_name}」的可复用汇总层，供 ADS 和安全下钻复用。",
        },
        "ads_design": {
            "table_name": f"ads.ads_{metric_code}_board",
            "grain": ["stat_date", "business_domain"],
            "measures": [metric_code],
            "description": f"面向看板和 AI 问数的「{display_name}」服务层结果表。",
        },
        "sql_draft": _sql_draft(metric_code, source_table, metric),
        "dq_rules": [
            {
                "rule_code": f"DQ_{metric_code.upper()}_001",
                "rule_name": "统计日期不能为空",
                "check_sql": f"SELECT COUNT(1) AS fail_cnt FROM dws.dws_{metric_code}_1d WHERE stat_date IS NULL;",
                "severity": "CRITICAL",
            },
            {
                "rule_code": f"DQ_{metric_code.upper()}_002",
                "rule_name": "核心指标不能为空或负数",
                "check_sql": f"SELECT COUNT(1) AS fail_cnt FROM ads.ads_{metric_code}_board WHERE {metric_code} IS NULL OR {metric_code} < 0;",
                "severity": "HIGH",
            },
        ],
        "lineage": {
            "upstream": sources,
            "dws": f"dws.dws_{metric_code}_1d",
            "ads": f"ads.ads_{metric_code}_board",
            "known_graph_nodes": list(lineage_graph.keys())[:8] if isinstance(lineage_graph, dict) else [],
        },
        "drilldown_policy": {
            "default_layer": "ADS/DWS",
            "detail_layer": "DWD only through sampled drill-down tools",
            "forbidden": ["free-form ODS scan", "SELECT *", "queries without date range", "sensitive identity fields"],
            "required_guards": ["read-only", "LIMIT <= 100", "date filter", "table whitelist", "audit log"],
        },
        "warnings": warnings,
    }
