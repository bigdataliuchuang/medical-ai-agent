# Medical AI Agent

医疗数据治理平台 AI 对话模块。

## 启动

```bash
cp .env.example .env
# 填写 .env 中的 API Key 和 Doris 连接配置
uvicorn main:app --reload --port 8000
```

## 接口

- POST /api/chat — 对话接口
- GET  /api/health — 健康检查
