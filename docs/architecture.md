# 医疗 Data Agent Runtime — 架构文档

## 一句话定位

面向医疗数仓场景的 Data Agent Runtime：不只是 Text-to-SQL，而是把医疗元数据、指标口径、数据质量规则、权限控制和执行日志全部串联起来的 Agent 工作流系统。

---

## 五层架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    用户自然语言问题                            │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 5: 任务调度层 (Task Scheduling)                        │
│  TaskPlanner → 拆解复杂多步问题                               │
│  TaskScheduler → 按依赖顺序执行，上游结果注入下游上下文        │
│  文件: agent/planner.py  agent/scheduler.py                  │
└────────────────────────┬─────────────────────────────────────┘
                         │ 简单问题直接走 ReAct
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 1+2: LLM 推理层 + 工具调用层 (ReAct Agent)            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Thought → Action → Observation → ... → Answer       │    │
│  │                                                       │    │
│  │  Tools:                                              │    │
│  │  • search_metadata   搜索元数据目录（GraphRAG）       │    │
│  │  • generate_sql      基于上下文生成 SQL               │    │
│  │  • validate_sql      SQL 安全校验                     │    │
│  │  • execute_sql       只读 SQL 执行（Doris/DuckDB）    │    │
│  │  • analyze_result    结果分析与业务解释               │    │
│  └─────────────────────────────────────────────────────┘    │
│  文件: agent/loop.py  agent/tools.py  agent/tool_impls.py   │
└────────────────────────┬─────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
┌─────────────────┐          ┌──────────────────────┐
│  Layer 3: 记忆层 │          │  Layer 4: 技能沉淀层  │
│  ConversationMemory        │  SkillStore + SkillLoader│
│  按 session 存历史          │  成功模式持久化        │
│  SQLite, TTL 过期          │  Jaccard 相似度检索    │
│  agent/memory.py           │  Skills → Prompt注入   │
└─────────────────┘          │  agent/skill_store.py  │
                             │  agent/skill_loader.py │
                             │  skills/*.md           │
                             └──────────────────────┘
```

---

## 模块清单

### Agent 核心

| 模块 | 文件 | 职责 |
|------|------|------|
| Workflow 编排器 | `agent/workflow.py` | 顶层入口，串联五层 |
| ReAct Loop | `agent/loop.py` | Thought→Action→Obs 推理循环 |
| Tool Registry | `agent/tools.py` | 工具注册、调用、鉴权 |
| Tool 实现 | `agent/tool_impls.py` | 5 个核心工具具体实现 |
| Task Planner | `agent/planner.py` | 复杂问题拆解为子任务 |
| Task Scheduler | `agent/scheduler.py` | 按依赖顺序执行子任务 |
| Memory | `agent/memory.py` | 对话历史（SQLite, TTL） |
| Skill Store | `agent/skill_store.py` | 技能沉淀，Jaccard检索 |
| Skill Loader | `agent/skill_loader.py` | 加载 Skill MD，注入Prompt |
| Confidence Scorer | `agent/confidence.py` | 多维置信度评分 |
| Result Analyzer | `agent/result_analyzer.py` | 结果解释与业务洞察 |

### SQL 安全

| 模块 | 文件 | 职责 |
|------|------|------|
| SQL Guard | `text2sql/sql_guard.py` | 七规则安全校验 |
| SQL Generator | `text2sql/generator.py` | LLM SQL生成 |
| Prompt Builder | `text2sql/prompt_builder.py` | 上下文注入 |

**SQL Guard 七条规则：**
1. 高危关键词拦截（DROP/DELETE/UPDATE/INSERT/TRUNCATE/ALTER/CREATE）
2. 仅允许 SELECT
3. 禁止 SELECT *
4. 表必须带 Schema 限定
5. 必须有 LIMIT
6. 时间范围过滤（可选配置）
7. 敏感字段检测（id_card/phone/patient_name等8个字段）

### 存储与可观测性

| 模块 | 文件 | 职责 |
|------|------|------|
| Session DB | `storage/session_db.py` | 5张SQLite表，全链路记录 |
| Audit Logger | `agent/audit.py` | 审计日志协议与实现 |

**5 张 SQLite 表：**
- `agent_session` — 会话主表
- `agent_message` — 用户/助手消息
- `agent_tool_call` — 工具调用记录
- `agent_sql_audit` — SQL 安全审计
- `agent_eval_result` — 评测结果

### 检索增强（GraphRAG）

| 模块 | 文件 | 职责 |
|------|------|------|
| GraphRAG Retriever | `graphrag/retriever.py` | 向量+图混合检索 |
| Context Builder | `graphrag/context_builder.py` | 构建 TextToSqlContext |
| Milvus Store | `graphrag/milvus_store.py` | 向量索引存储 |

### 医疗元数据

```
metadata/
  schema_catalog.yaml      # 表目录（表名、注释、关联关系）
  column_catalog.yaml      # 字段目录（含敏感标记）
  metric_catalog.yaml      # 指标口径（定义、计算逻辑、维度）
  drug_dict.yaml           # 药品字典（20条抗肿瘤药品）
  diagnosis_dict.yaml      # ICD-10 诊断编码（15条肿瘤相关）
  dq_rule_catalog.yaml     # DQ规则目录
  lineage_graph.yaml       # 数据血缘图

skills/
  anti_tumor_drug_usage.md       # 抗肿瘤药物使用分析 SOP
  diagnosis_quality_check.md     # 诊断数据质量检查
  visit_quality_check.md         # 就诊数据质量检查
  patient_count_analysis.md      # 患者人数统计
  drug_expense_analysis.md       # 药品费用分析
  lab_abnormal_analysis.md       # 检验异常分析
  dwd_table_design.md            # DWD 建模辅助
  sql_optimization.md            # SQL 优化建议
```

### 评测体系

| 模块 | 文件 | 职责 |
|------|------|------|
| Eval Runner | `evaluation/eval_runner.py` | 自动评测，输出报告 |
| Benchmark Questions | `evaluation/benchmark_questions.yaml` | 30 道标准测试题 |

**评测指标：**
- SQL 语法通过率（sqlglot 解析）
- SQL 安全合规率（SqlGuard 校验）
- 表选择准确率（Jaccard 相似度）
- 按 domain / difficulty 分组分析
- 耗时统计

---

## 完整调用流程

```
用户: "统计本月肺癌患者抗肿瘤药物费用"
       │
       ▼
AgentWorkflow.run(question, session_id)
       │
       ├─ 1. ConversationMemory.get_history(session_id)
       │     → 取前5轮对话上下文
       │
       ├─ 2. SkillStore.retrieve_similar(question)
       │     → 检索历史相似成功案例
       │
       ├─ 3. SkillLoader.match_skill(question, skills)
       │     → 匹配 anti_tumor_drug_usage.md
       │     → 注入 SOP 到 system prompt
       │
       ├─ 4. 问题复杂度判断
       │     ├─ 简单 → ReActAgent.run()
       │     └─ 复杂 → TaskPlanner.plan() → TaskScheduler.execute_plan()
       │
       ├─ [ReAct Loop]
       │   ├─ Thought: 需要查询肺癌诊断 + 抗肿瘤药物医嘱
       │   ├─ Action: search_metadata("肺癌 抗肿瘤药物")
       │   │   → GraphRAG 返回: dwd_diagnosis, dwd_order, dim_drug_dict
       │   ├─ Action: generate_sql(context)
       │   │   → SQL: SELECT ... FROM dwd.dwd_diagnosis JOIN dwd.dwd_order ...
       │   ├─ Action: validate_sql(sql)
       │   │   → SqlGuard 七规则校验 → PASSED, risk=LOW
       │   ├─ Action: execute_sql(sql)
       │   │   → Doris 返回 15 行数据
       │   ├─ Action: analyze_result(question, sql, result)
       │   │   → 生成业务解释 + 下钻建议
       │   └─ Final Answer: "本月肺癌患者抗肿瘤药物费用为 XXX 万元..."
       │
       ├─ 5. ConversationMemory.save_turn(session_id, Q, A)
       ├─ 6. SkillStore.save_skill(question, sql, answer)
       └─ 7. 返回 WorkflowResult
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| LLM | Claude API (claude-sonnet-4-6) |
| 向量数据库 | Milvus Lite（本地）/ Milvus（生产） |
| 查询数据库 | Apache Doris（生产）/ DuckDB（本地测试） |
| 会话存储 | SQLite |
| SQL 解析 | sqlglot |
| 元数据格式 | YAML |
| API 框架 | FastAPI |
| 测试框架 | pytest |
