import os
import json
from enum import Enum
from dotenv import load_dotenv
from agent.sql_gen import _call_llm

load_dotenv()


class Intent(str, Enum):
    QUERY_DATA = "QUERY_DATA"
    FOLLOWUP = "FOLLOWUP"
    ASK_CONCEPT = "ASK_CONCEPT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


INTENT_SYSTEM = """你是一个意图分类器。根据用户问题和对话历史，判断问题意图。

意图类别：
- QUERY_DATA：需要查询数据库获取数据（如"本月肺癌患者多少人"、"DQ评分趋势"）
- FOLLOWUP：追问上一轮查询结果（如"那按科室分呢"、"再看看上个月的"、"展开说说"）
- ASK_CONCEPT：询问概念或定义（如"什么是MPI"、"DQ评分怎么算的"）
- OUT_OF_SCOPE：与医疗数据治理无关（如"今天天气如何"、"帮我写首诗"）

规则：
1. 如果有对话历史且当前问题明显引用上一轮（使用"那"、"再"、"按XX分"、"展开"等），判定为 FOLLOWUP
2. 只返回 JSON：{"intent": "类别", "confidence": 0.0-1.0}
3. 不要任何解释文字"""


def classify(question: str, history: list = None) -> dict:
    history = history or []
    messages = []

    # 取最近 3 轮历史作为上下文
    recent = history[-6:] if history else []
    if recent:
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        messages.append({"role": "user", "content": f"对话历史：\n{history_text}\n\n当前问题：{question}"})
    else:
        messages.append({"role": "user", "content": f"当前问题：{question}"})

    try:
        text = _call_llm(INTENT_SYSTEM, messages)
        # 提取 JSON
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        result = json.loads(text)
        intent = result.get("intent", "QUERY_DATA")
        confidence = float(result.get("confidence", 0.8))
        # 验证 intent 合法
        if intent not in [e.value for e in Intent]:
            intent = "QUERY_DATA"
        return {"intent": intent, "confidence": confidence}
    except Exception:
        # 分类失败时默认 QUERY_DATA，不阻断流程
        return {"intent": "QUERY_DATA", "confidence": 0.5}
