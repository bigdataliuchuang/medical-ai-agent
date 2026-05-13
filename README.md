# Medical AI Data Agent

医疗数据治理 AI 问数服务，面向 Doris / DuckDB 医疗数仓提供自然语言查询、GraphRAG 元数据检索、Text-to-SQL、安全执行、结果解释、审计和数仓开发辅助能力。

## 三仓定位

| 仓库 | 定位 | 关系 |
|------|------|------|
| `medical-data-governance` | 数仓治理层 | 提供 ODS -> ADS SQL、DQ 规则、MPI/MDM、指标口径、血缘和 Doris 服务层 |
| `medical-ai-agent` | AI 问数服务层 | 读取元数据和 Doris / DuckDB，生成安全 SQL 并返回解释 |
| `medical-platform` | 可视化平台层 | 通过右下角 AI 助手浮窗调用本服务，同时展示治理看板 |

推荐三个仓库保持同级目录：

```text
github/
├── medical-data-governance/
├── medical-ai-agent/
└── medical-platform/
```

## 当前入口

本仓库保留两套服务入口：

| 入口 | 推荐场景 | 说明 |
|------|----------|------|
| `src/ai_data_agent/` | 生产化实现 | GraphRAG、ReAct Agent、CLI、评估、健康检查、`/api/v1/*` API |
| `main.py` + `agent/` + `api/` | 平台兼容入口 | 兼容 `medical-platform` 浮窗集成，提供 `/api/chat`、`/api/dev/*` 等旧版接口 |

新能力优先放在 `src/ai_data_agent/`。旧版入口继续保留，用于平台集成和已有 API 兼容。

## 核心能力

### 自然语言问数链路

```text
用户问题
  -> GraphRAG 检索元数据
  -> 汇总表结构、指标口径、DQ 规则、Join 路径和血缘上下文
  -> LLM 生成 SQL
  -> SQLGlot 安全校验
  -> Doris 或 DuckDB 执行只读查询
  -> 结果解释、失败分类和审计记录
```

### ReAct Agent 链路

`POST /api/v1/agent/query` 会让 Agent 逐步调用工具：

- `search_metadata`：搜索表、指标、DQ 规则和血缘上下文。
- `generate_sql`：基于上下文生成 SQL。
- `validate_sql`：校验 SQL 安全规则。
- `execute_sql`：执行只读查询。
- `analyze_result`：解释查询结果并给出后续建议。

### 数仓开发助手

旧版兼容 API 中提供指标开发辅助能力：

- 根据业务需求匹配或生成指标编码。
- 生成 DWS / ADS 表设计草案。
- 生成 SQL 草稿、DQ 规则和血缘说明。
- 输出可落盘的 YAML / Markdown 指标资产。

### Semantic Layer 状态

项目现在包含平台化 Semantic Layer 后端的第一版，并在 `medical-platform` 中提供前端管理/查询入口。

当前已具备：

- `metadata/semantic/datasets.yaml`：维护语义数据集和物理表映射。
- `metadata/semantic/dimensions.yaml`：维护统一维度、字段映射、层级和敏感级别。
- `metadata/semantic/metrics.yaml`：维护指标公式、版本、状态、owner、审批信息和血缘。
- `metadata/semantic/policies.yaml`：维护租户/角色到指标、维度和敏感字段的访问策略。
- `src/ai_data_agent/semantic_service/`：提供 catalog、DSL、policy、compiler、service、audit 和 API。
- `/api/v1/semantic/*`：提供指标、维度、数据集、SQL 编译、语义查询和审计事件接口。
- `medical-platform` 前端新增 `语义层` 页面，支持目录浏览、DSL 查询、SQL 预览、结果表格和审计查看。

当前还未形成完整能力：

- 审计事件还未持久化落库。
- 指标审批/发布/下线还只是元数据字段，尚未提供交互式工作流。
- 跨数据集 Join 编译暂未开放。
- 面向 BI 的稳定 API 契约还需要进一步固化。

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

如果使用生产化包入口：

```bash
pip install -e .
```

### 2. Pocket 本地演示

Pocket 模式使用 DuckDB + Milvus Lite，不需要启动 Doris 和独立 Milvus，适合本地验证。

```bash
cp .env.pocket.example .env
# 编辑 .env，填入 LLM_API_KEY / EMBEDDING_API_KEY 等配置

bash scripts/run_pocket_demo.sh
```

脚本会：

1. 初始化 `data/medical_dw.db` DuckDB 示例数仓。
2. 首次运行时构建 `data/medical_metadata.db` Milvus Lite 元数据索引。
3. 启动 Web/API 服务，默认地址为 `http://127.0.0.1:8000`。

重建元数据索引：

```bash
REBUILD_METADATA=1 bash scripts/run_pocket_demo.sh
```

### 3. 生产配置启动

准备配置：

```bash
cp .env.example .env
```

关键环境变量：

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

启动生产化 API：

```bash
ai-data-agent serve \
  --config config/application.example.yaml \
  --metadata-root metadata \
  --host 0.0.0.0 \
  --port 8000
```

也可以直接使用 Uvicorn：

```bash
AI_DATA_AGENT_CONFIG=config/application.example.yaml \
AI_DATA_AGENT_METADATA_ROOT=metadata \
uvicorn ai_data_agent.main:app --host 0.0.0.0 --port 8000
```

### 4. 兼容平台入口

`medical-platform/docker-compose.yml` 会从同级目录构建本仓库的 `Dockerfile.simple`，并把容器端口 `8000` 映射到宿主机 `8001`。

本地单独启动兼容 API：

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

兼容 API 用于：

- `POST /api/chat`：平台 AI 浮窗对话。
- `POST /api/index/rebuild`：重建旧版 schema 向量索引。
- `GET /api/audit/logs`：审计日志查询。
- `POST /api/dev/metric-plan`：生成指标开发方案。
- `POST /api/dev/metric-assets`：保存指标资产。

## Docker Compose

本仓库自带 `docker-compose.yml`，可启动 Milvus、Doris 和 AI Data Agent：

```bash
cp .env.example .env
docker compose up -d
```

该 Compose 更适合独立验证 AI Agent。若要运行完整可视化平台，请从 `medical-platform` 执行：

```bash
cd ../medical-platform
docker compose up --build
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

查询示例：

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "各科室抗肿瘤药物费用排名，显示科室名称",
    "top_k": 5,
    "max_rows": 20
  }'
```

### 兼容 API

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

## 项目结构

```text
medical-ai-agent/
├── src/ai_data_agent/       # 生产化包入口、CLI、API、配置和元数据加载
├── agent/                   # 旧版兼容 Agent pipeline
├── api/                     # 旧版兼容 FastAPI 路由
├── metadata/                # 表、字段、指标、DQ 规则、血缘和 Join 图
├── schema/                  # ADS 表 schema 示例
├── skills/                  # 领域分析技能说明
├── evaluation/              # 评测问题、期望指标和评测 runner
├── scripts/                 # Pocket demo 初始化与启动脚本
├── config/                  # application 配置模板
├── tests/                   # 单元与集成测试
├── main.py                  # 旧版兼容入口
└── pyproject.toml           # 生产化包与 CLI 配置
```

## 与数仓项目同步

当 `medical-data-governance` 中的 ADS 表、DQ 规则或指标口径变化后，需要同步检查本仓库：

- `metadata/schema_catalog.yaml`
- `metadata/metric_catalog.yaml`
- `metadata/dq_rule_catalog.yaml`
- `metadata/lineage_graph.yaml`
- `metadata/schema_graph.yaml`
- `evaluation/*.yaml` 和 `evaluation/questions.jsonl`

同步后建议运行：

```bash
pytest
```

## 开发与测试

```bash
pytest
pytest tests/test_sql_guard.py
pytest tests/integration/test_duckdb_query.py
```

如果只验证 CLI 和配置：

```bash
ai-data-agent health-check \
  --config config/application.example.yaml \
  --metadata-root metadata
```

## 生产约束

- 正式执行引擎优先使用 Doris。
- 正式向量检索使用 Milvus；Pocket 模式可使用 Milvus Lite。
- SQL 必须通过 SQLGlot 安全校验后才能执行。
- 查询失败时不允许伪造结果。
- Mock 和 DuckDB 仅用于本地演示、评测或测试隔离。
