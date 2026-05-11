import os
import yaml
from dataclasses import dataclass, field


@dataclass
class SchemaDoc:
    table_name: str
    full_text: str
    sample_questions: list = field(default_factory=list)


def load_all_schemas(schema_dir: str) -> list:
    schemas = []
    for f in sorted(os.listdir(schema_dir)):
        if not f.endswith(".yaml"):
            continue
        path = os.path.join(schema_dir, f)
        with open(path, encoding="utf-8") as fp:
            raw = yaml.safe_load(fp)
        if not raw or not raw.get("table_name"):
            continue

        doc = _to_schema_doc(raw)
        schemas.append(doc)
    return schemas


def _to_schema_doc(raw: dict) -> SchemaDoc:
    table = raw["table_name"]
    db = raw.get("database", "ads")
    desc = raw.get("description", "")
    domain = raw.get("business_domain", "")

    col_lines = []
    for c in raw.get("columns", []):
        col_lines.append(f"  {c['name']}({c.get('type', '')}): {c.get('description', '')}")
    col_text = "\n".join(col_lines)

    full_text = (
        f"表名：{db}.{table}\n"
        f"业务域：{domain}\n"
        f"描述：{desc}\n"
        f"字段：\n{col_text}"
    )

    return SchemaDoc(
        table_name=table,
        full_text=full_text,
        sample_questions=raw.get("sample_questions", []),
    )
