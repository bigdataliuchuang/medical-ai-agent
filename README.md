# Medical AI Data Agent

医疗数据治理 Data Agent，面向 Doris / DuckDB 医疗数仓提供自然语言问数、GraphRAG 元数据检索、Text2SQL、安全执行、结果解释、审计和数仓开发辅助能力。

当前仓库同时保留两套入口：

- `src/ai_data_agent/`：推荐的生产化实现，包含 GraphRAG、ReAct Agent、CLI、评估、健康检查和 `/api/v1/*` API。
- `main.py` + `agent/` + `api/`：兼容旧版平台浮窗集成的轻量 FastAPI 入口，继续提供 `/api/chat`、`/api/dev/*` 等接口。

## 核心能力

### 生产化查询链路

```
用户问题
  -> GraphRAG 检索元数据（Milvus / Milvus Lite + schema graph + lineage graph）
  -> 构建 Text2SQL 上下文（表、指标、DQ 规则、Join 路径）
  -> LLM 生成 SQL
  -> SQLGlot 安全校验（只读、Schema 白名单、禁 SELECT *、限制 LIMIT）
  -> Doris 或 DuckDB 执行
  -> 结果分析与自然语言解释
  -> 审计记录与会话记忆
```

### ReAct Agent 链路

`/api/v1/agent/query` 会让 Agent 按步骤调用工具：

- `search_metadata`：搜索表、指标、DQ 规则和血缘上下文。
- `generate_sql`：基于上下文生成 SQL。
- `validate_sql`：校验 SQL 安全规则。
- `execute_sql`：执行只读查询。
- `analyze_result`：解释查询结果并给出后续建议。

### 数仓开发助手

最新版本增加了指标开发辅助接口：

- 根据业务需求匹配或生成指标编码。
- 生成 DWS / ADS 表设计草案。
- 生成 SQL 草稿、DQ 规则和血缘说明。
- 输出可落盘的 YAML / Markdown 指标资产。

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

如使用 `pyproject.toml` 的生产化包入口，也可以在虚拟环境中安装当前项目：

```bash
pip install -e .
```

### 2. Pocket 本地演示（DuckDB + Milvus Lite）

Pocket 模式适合本地验证，不需要启动 Doris 和独立 Milvus。

```bash
cp .env.pocket.example .env
# 编辑 .env，填入 LLM_API_KEY / EMBEDDING_API_KEY 等配置

bash scripts/run_pocket_demo.sh
```

脚本会完成三件事：

1. 初始化 `data/medical_dw.db` DuckDB 示例数仓。
2. 首次运行时构建 `data/medical_metadata.db` Milvus Lite 元数据索引。
3. 启动 Web/API 服务，默认地址为 `http://127.0.0.1:8000`。

重新构建元数据索引：

```bash
REBUILD_METADATA=1 bash scripts/run_pocket_demo.sh
```

### 3. 生产配置启动（Doris + Milvus）

准备环境变量：

```bash
cp .env.example .env
```

生产化配置文件示例在 `config/application.example.yaml`，关键配置包括：

```env
DORIS_HOST=127.0.0.1
DORIS_PORT=9030
DORIS_USER=root
DORIS_PASSWORD=your_password
DORIS_DATABASE=ads

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION=medical_metadata

LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY=sk-xxxx

EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=sk-xxxx
EMBEDDING_DIMENSION=1024
```

静态启动检查：

```bash
ai-data-agent health-check \
  --config config/application.example.yaml \
  --metadata-root metadata
```

初始化 Milvus 元数据：

```bash
ai-data-agent ingest-metadata \
  --config config/application.example.yaml \
  --metadata-root metadata \
  --create-collection
```

启动服务：

```bash
ai-data-agent serve \
  --config config/application.example.yaml \
  --metadata-root metadata \
  --host 0.0.0.0 \
  --port 8000
```

也可以直接用 Uvicorn：

```bash
AI_DATA_AGENT_CONFIG=config/application.example.yaml \
AI_DATA_AGENT_METADATA_ROOT=metadata \
uvicorn ai_data_agent.main:app --host 0.0.0.0 --port 8000
```

### 4. 旧版兼容入口

如需要使用旧版 `/api/chat`、`/api/index/rebuild` 或前端平台浮窗集成：

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

## API

### 生产化 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 本地查询控制台 |
| `POST` | `/api/v1/query` | 单轮自然语言问数，返回 SQL、数据、解释和上下文摘要 |
| `POST` | `/api/v1/agent/query` | ReAct 多步 Agent 查询，返回工具调用轨迹 |
| `GET` | `/api/v1/sessions/{session_id}/history` | 获取会话历史 |
| `DELETE` | `/api/v1/sessions/{session_id}` | 删除会话 |
| `GET` | `/health` | 基础健康检查 |
| `GET` | `/health/ready` | 就绪检查 |

单轮查询示例：

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "各科室抗肿瘤药物费用排名，显示科室名称",
    "top_k": 5,
    "max_rows": 20
  }'
```

Agent 查询示例：

```bash
curl -X POST http://localhost:8000/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-session",
    "question": "查询抗肿瘤药物汇总中科室缺失的数据质量问题",
    "max_steps": 8,
    "max_rows": 50
  }'
```

### 旧版兼容 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 旧版对话接口，返回答案、SQL 和数据 |
| `GET` | `/api/chat/history` | 旧版会话历史 |
| `GET` | `/api/chat/suggestions` | 示例问题推荐 |
| `POST` | `/api/index/rebuild` | 后台重建旧版 schema 向量索引 |
| `GET` | `/api/audit/logs` | 查询旧版 JSONL 审计日志 |
| `POST` | `/api/dev/metric-plan` | 生成指标开发方案 |
| `POST` | `/api/dev/metric-assets` | 保存指标方案为 YAML / Markdown |
| `GET` | `/health` | 健康检查 |

指标开发方案示例：

```bash
curl -X POST http://localhost:8001/api/dev/metric-plan \
  -H "Content-Type: application/json" \
  -d '{
    "requirement": "帮我设计一个抗肿瘤药物使用强度指标，支持按科室和药品下钻",
    "domain": "药物监测"
  }'
```

## CLI

| 命令 | 说明 |
|------|------|
| `ai-data-agent health-check` | 校验配置、元数据和可选外部依赖 |
| `ai-data-agent ingest-metadata` | 将 `metadata/` 中的元数据切片并写入 Milvus |
| `ai-data-agent serve` | 启动生产化 FastAPI 服务 |
| `ai-data-agent evaluate` | 基于 `evaluation/questions.jsonl` 批量评估 Text2SQL 链路 |

评估示例：

```bash
ai-data-agent evaluate \
  --config config/application.pocket.yaml \
  --metadata-root metadata \
  --questions evaluation/questions.jsonl \
  --output data/evaluation-report.json \
  --dry-run
```

## SQL 安全规则

| 规则 | 说明 |
|------|------|
| 只允许 `SELECT` | 生产化 SQL guard 拒绝非只读语句 |
| 禁止多语句 | 只允许单条 SQL |
| 禁止 `SELECT *` | 避免无边界明细扫描 |
| Schema 白名单 | 默认允许 `dwd`、`dim`、`dws`、`ads`、`dq`、`mpi`、`mdm` |
| 强制 `LIMIT` | Agent 生成查询必须带限制 |
| 表必须带 Schema | 防止误查默认库或同名表 |
| 执行器只读 | Doris / DuckDB executor 均按只读查询路径设计 |

## 目录结构

```text
medical-ai-agent/
├── src/ai_data_agent/          # 推荐的生产化包
│   ├── api/                    # /api/v1 路由、依赖、鉴权、限流
│   ├── agent/                  # ReAct loop、工具、记忆、审计、结果分析
│   ├── executor/               # Doris / DuckDB 查询执行器
│   ├── graphrag/               # 元数据切片、向量检索、图检索、上下文构建
│   ├── semantic_layer/         # 指标解析
│   ├── text2sql/               # Prompt、LLM 客户端、SQL 生成与校验
│   ├── evaluation/             # 批量评估与回归检测
│   └── observability/          # 日志与成本观测
├── agent/                      # 旧版兼容 Agent 模块
├── api/                        # 旧版兼容 API，包括 /api/dev 数仓开发助手
├── metadata/                   # 指标、Schema、血缘、DQ 规则元数据
├── schema/                     # 旧版 ADS schema YAML
├── scripts/                    # Pocket Demo 初始化与启动脚本
├── tests/                      # 单元、集成、回归和兼容性测试
├── config/                     # application.*.yaml 配置
├── data/                       # 本地 DuckDB / Milvus Lite / 会话数据
├── Dockerfile
├── Dockerfile.simple
├── docker-compose.yml
├── pyproject.toml
└── requirements.txt
```

## 测试

```bash
pytest
```

常见重点测试：

```bash
pytest tests/test_sql_guard.py
pytest tests/test_graphrag_retriever.py
pytest tests/test_text2sql_generation.py
pytest tests/test_warehouse_dev_assets.py
```

## 部署

完整 Linux 部署步骤见 `DEPLOYMENT.md`，包括：

- Docker Compose 全栈部署 Doris、Milvus 和 Agent。
- Conda + systemd 手动部署。
- 元数据初始化、健康检查和常用运维命令。

## 相关仓库

| 仓库 | 说明 |
|------|------|
| [medical-platform](https://github.com/bigdataliuchuang/medical-platform) | 前端平台，集成 AI 对话浮动组件 |
| [medical-data-governance](https://github.com/bigdataliuchuang/medical-data-governance) | 医疗数仓与数据治理底座 |
