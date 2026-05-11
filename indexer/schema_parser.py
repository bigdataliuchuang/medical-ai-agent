# Schema YAML 解析 - 待实现（Phase 2）
import os, yaml

def load_all_schemas(schema_dir: str) -> list:
    schemas = []
    for f in os.listdir(schema_dir):
        if f.endswith(".yaml"):
            with open(os.path.join(schema_dir, f)) as fp:
                schemas.append(yaml.safe_load(fp))
    return schemas
