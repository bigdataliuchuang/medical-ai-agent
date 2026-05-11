# Medical AI Data Agent

医疗数据治理 AI 数据助手，提供自然语言查询医疗数仓（Doris ADS 层）能力。

## 核心链路

```
用户问题
  → 意图分类（QUERY_DATA / FOLLOWUP / ASK_CONCEPT / OUT_OF_SCOPE）
  → Schema 检索（Milvus 向量检索，降级为 YAML 全量）
  → Prompt 构建（带多轮对话历史）
  → SQL 生成（Claude LLM）
  → SQL 安全校验（SQLGlot AST + 表白名单 + 禁 SELECT * + 自动 LIMIT）
  → Doris 执行（失败时自动修复重试 2 次）
  → 结果自然语言解释
  → 审计日志写入（JSONL，按日期分文件）
```

## 快速启动

### 环境变量

```bash
cp .env.example .env
```

`.env` 关键配置：

```env
ANTHROPIC_API_KEY=sk-ant-xxxx
LLM_MODEL=claude-haiku-4-5-20251001

DORIS_HOST=192.168.241.128
DORIS_PORT=9030
DORIS_USER=root
DORIS_PASSWORD=your_password
DORIS_DATABASE=ads

MILVUS_HOST=localhost
MILVUS_PORT=19530
```

### 直接运行

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
```

### Docker

```bash
docker build -f Dockerfile.simple -t medical-ai-agent .
docker run -p 8001:8000 --env-file .env medical-ai-agent
```

### 配合 medical-platform 启动

```bash
# 在 medical-platform 目录下
docker compose up --build
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送对话，返回答案 + SQL + 数据 |
| GET | `/api/chat/history` | 获取会话历史 |
| GET | `/api/chat/suggestions` | 随机推荐问题（来自 schema YAML） |
| POST | `/api/index/rebuild` | 重建 Milvus 向量索引（后台执行） |
| GET | `/api/audit/logs` | 查询审计日志（支持日期、用户、分页） |
| GET | `/health` | 健康检查 |

### 对话示例

```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-001",
    "message": "今天各数据层的DQ评分是多少？",
    "user_id": "admin"
  }'
```

返回：

```json
{
  "answer": "今天 ODS 层 DQ 评分为 87.5，DWD 层 92.0，MPI 层 89.3，ADS 层 94.1。",
  "sql": "SELECT data_layer, dq_score FROM ads.ads_dq_result_summary WHERE stat_date = CURDATE() LIMIT 100",
  "data": [...],
  "row_count": 4,
  "status": "success",
  "session_id": "test-001"
}
```

## 初始化向量索引

首次启动后，调用一次以将 `schema/` 下的 YAML 编码入 Milvus：

```bash
curl -X POST http://localhost:8001/api/index/rebuild
```

未初始化时自动降级使用内置 Schema，AI 功能正常可用。

## 目录结构

```
medical-ai-agent/
├── main.py              # FastAPI 入口，注册 4 个路由
├── agent/
│   ├── pipeline.py      # 8步主流程编排
│   ├── intent.py        # LLM 意图分类器
│   ├── prompt_builder.py # SQL prompt 构建（含多轮历史）
│   ├── sql_gen.py       # SQL 生成 / 修复 / 概念解释
│   ├── sql_guard.py     # SQLGlot AST 安全校验 + add_limit()
│   ├── retriever.py     # Milvus 检索 + YAML 降级
│   └── executor.py      # PyMySQL → Doris 执行
├── api/
│   ├── chat.py          # /api/chat 路由
│   ├── index.py         # /api/index/rebuild（后台任务）
│   ├── audit.py         # /api/audit/logs
│   └── health.py        # /health
├── memory/
│   └── session_store.py # SQLite 持久化 Session（重启不丢）
├── audit/
│   └── logger.py        # JSONL 审计日志 + 分页查询
├── indexer/
│   ├── schema_parser.py # YAML → SchemaDoc 解析
│   └── build_index.py   # Milvus 向量索引构建
├── schema/              # 6 张 ADS 表的结构和示例问题
├── requirements.txt
├── Dockerfile.simple    # 轻量镜像（python:3.11-slim）
└── .env.example
```

## SQL 安全规则

| 规则 | 实现 |
|------|------|
| 只允许 SELECT | executor + sql_guard 双重检查 |
| 表白名单 | 仅允许 ADS/DQ 层 9 张表 |
| 禁止 SELECT * | SQLGlot AST 检测 `exp.Star` |
| 自动注入 LIMIT | 无 LIMIT 子句时自动加 LIMIT 100 |
| 禁止多语句 | 检测 `;` 分隔符 |
| 查询超时 | read_timeout=30s |

## 相关仓库

| 仓库 | 说明 |
|------|------|
| [medical-platform](https://github.com/bigdataliuchuang/medical-platform) | 前端平台，集成了 AI 对话浮动组件 |
| [medical-data-governance](https://github.com/bigdataliuchuang/medical-data-governance) | 数仓层，提供 ADS 层数据和 DQ 规则 |
