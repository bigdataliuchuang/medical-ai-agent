# Medical Data Governance Data Agent

生产级医疗数据治理智能分析模块。

本模块在现有医疗湖仓治理平台之上新增智能分析入口，正式链路采用：

```text
Milvus + GraphRAG + Semantic Layer + Text-to-SQL + SQLGlot + Doris + Audit
```

小机器或本机开发可使用口袋版链路：

```text
Milvus Lite + GraphRAG + Semantic Layer + Text-to-SQL + SQLGlot + DuckDB
```

## 1. 模块定位

`ai-data-agent/` 不替代现有 `sql/medical/`、`scripts/medical/`、`docs/medical-governance/` 主线。它负责把医疗元数据、指标口径、DQ 规则、数仓血缘和 Doris 服务查询组织成可审计的 Data Agent 能力。

核心流程：

```text
用户问题
  -> Milvus 检索元数据和规则
  -> YAML Graph 扩展 Join 路径和血缘
  -> Semantic Layer 解析指标口径
  -> Text-to-SQL 生成 Doris SQL
  -> SQLGlot 安全校验
  -> Doris 执行真实查询
  -> Agent 输出解释、异常分析和下钻建议
```

## 2. 生产原则

- Doris 是正式 SQL 执行引擎。
- Milvus 是正式向量检索引擎。
- SQL 必须经过 SQL Guard 后才能执行。
- 查询失败时不允许大模型伪造结果。
- 测试桩只用于单元测试隔离，不作为正式运行路径。
- Doris、Milvus、LLM、Embedding 配置缺失时服务应启动失败。

## 3. 目录说明

```text
ai-data-agent/
├── metadata/             # 表结构、指标口径、DQ 规则、Join/血缘图
├── graphrag/             # Milvus ingestion/retriever 和 YAML Graph 上下文构建
├── semantic_layer/       # 指标语义层
├── text2sql/             # Doris SQL 生成与 SQL Guard
├── executor/             # Doris 查询执行器
├── agent/                # Medical Data Agent 编排入口
├── evaluation/           # 生产问题评测集
└── config/               # 配置模板、白名单和健康检查约束
```

## 4. 阶段边界

第一阶段：

- Milvus 作为向量库。
- YAML 文件维护 Schema Graph、Lineage Graph 和指标依赖。
- Doris 执行真实 DWS/ADS 查询。
- 当前已提供元数据 chunk 生成、Embedding 客户端契约、Milvus store 接口、ingestion 服务和 GraphRAG retriever 骨架。
- 当前已提供 GraphRAG Context Builder，可输出 Text-to-SQL 所需的召回来源、相关表、指标口径、DQ 规则、Join 路径和血缘上下文。
- 当前已提供 Text-to-SQL prompt builder、OpenAI-compatible LLM client、SQL 生成服务和 SQL Guard 集成。

第二阶段：

- 当多跳血缘、影响分析和图谱可视化复杂度提升后，可将 YAML Graph 升级为 Neo4j 或 NebulaGraph。

## 5. 本地验证

不依赖外部服务的基础测试：

```bash
cd ai-data-agent
python -m pytest tests -q
```

正式 ingestion 和查询必须配置真实 Milvus、Embedding、Doris 和 LLM 服务。

## 6. 口袋版本地运行

口袋版用于 MacBook 或 2C2G 小服务器，不启动 Doris、Flink、SeaTunnel 或 Milvus Docker。它用 DuckDB 执行本地样例 SQL，用 Milvus Lite 存元数据向量。

```bash
cd ai-data-agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"

cp .env.pocket.example .env
# 修改 .env 里的 DashScope API Key

python scripts/init_pocket_duckdb.py

ai-data-agent ingest-metadata \
  --config config/application.pocket.yaml \
  --metadata-root metadata \
  --create-collection

ai-data-agent serve \
  --config config/application.pocket.yaml \
  --metadata-root metadata \
  --host 127.0.0.1 \
  --port 8000
```

启动后可以测试：

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question":"各科室抗肿瘤药物费用排名", "top_k": 2, "max_rows": 10}'
```

也可以用一键脚本完成 DuckDB 初始化、必要时初始化 Milvus Lite，并启动查询页面：

```bash
./scripts/run_pocket_demo.sh

# 元数据有变更时强制重建 Milvus Lite：
REBUILD_METADATA=1 ./scripts/run_pocket_demo.sh
```

浏览器打开：

```text
http://127.0.0.1:8000/
```

口袋版配置入口是 `config/application.pocket.yaml`：

- `executor.type=duckdb`：查询本地 `data/medical_dw.db`
- `milvus.mode=lite`：使用本地 `data/medical_metadata.db`
- `audit.sink=none`：本地不写 Doris 审计表
- SQL Guard 仍然开启，只允许白名单 schema 下的 `SELECT`

本地连接远端 Doris、Milvus 和大模型服务时，建议使用 `.env` 管理真实地址和密钥：

```bash
cp ai-data-agent/.env.example ai-data-agent/.env
cp ai-data-agent/config/application.local.example.yaml ai-data-agent/config/application.local.yaml
```

然后修改 `ai-data-agent/.env` 中的 Doris、Milvus、LLM 和 Embedding 配置。`application.local.yaml` 保留配置结构，真实敏感值从 `.env` 或系统环境变量读取；这两个本地文件不会提交到仓库。

## 7. 生产运维命令

静态启动检查，只校验配置和元数据完整性：

```bash
ai-data-agent health-check \
  --config ai-data-agent/config/application.local.yaml \
  --metadata-root ai-data-agent/metadata
```

动态启动检查，会连接真实 Milvus、Embedding 服务和 Doris：

```bash
ai-data-agent health-check \
  --config ai-data-agent/config/application.local.yaml \
  --metadata-root ai-data-agent/metadata \
  --dynamic
```

元数据入 Milvus：

```bash
ai-data-agent ingest-metadata \
  --config ai-data-agent/config/application.local.yaml \
  --metadata-root ai-data-agent/metadata
```

首次受控初始化 Milvus collection 时才允许使用：

```bash
ai-data-agent ingest-metadata \
  --config ai-data-agent/config/application.local.yaml \
  --metadata-root ai-data-agent/metadata \
  --create-collection
```

## 7. 关联文档

- `docs/medical-governance/ai-data-agent-architecture.md`
- `docs/medical-governance/ai-data-agent-implementation-plan.md`
- `docs/medical-governance/ai-data-agent-production-design.md`
