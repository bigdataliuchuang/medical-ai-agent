# Prompt 构建 - 待实现（Phase 3）

def build_prompt(question: str, schema_context: str, history: list) -> str:
    return f"问题：{question}\n\n可用表结构：\n{schema_context}"
