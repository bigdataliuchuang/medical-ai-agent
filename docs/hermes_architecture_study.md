# Hermes 架构借鉴分析

## 一、Hermes Agent 核心架构概述

Hermes Agent 是一类以"持续执行工作流"为核心的 Agent 系统，与一次性问答（Single-turn Q&A）的本质区别在于它把大语言模型嵌入到一个可以循环、可以调用工具、可以积累经验的运行时（Runtime）之中。其核心设计思想可以归纳为以下五层：

```
┌─────────────────────────────────────┐
│  Layer 5: 任务调度层                 │  复杂任务拆解与依赖编排
├─────────────────────────────────────┤
│  Layer 4: 技能沉淀层                 │  成功经验持久化与复用
├─────────────────────────────────────┤
│  Layer 3: 记忆层                     │  跨轮次对话上下文管理
├─────────────────────────────────────┤
│  Layer 2: 工具调用层                 │  外部能力注册与统一调度
├─────────────────────────────────────┤
│  Layer 1: LLM 推理层                 │  ReAct 多步推理循环
└─────────────────────────────────────┘
```

这五层架构形成一个从"单步推理"到"持续工作流"的递进关系：
- Layer 1+2 解决"模型能调用什么工具"
- Layer 3 解决"模型记得说过什么"
- Layer 4 解决"模型学到了什么"
- Layer 5 解决"如何把复杂任务拆成模型可以执行的片段"

---

## 二、医疗 Data Agent 对 Hermes 的借鉴

### 2.1 ReAct 推理循环（Layer 1）

**借鉴点：** Hermes 采用 ReAct（Reasoning + Acting）模式，即 Thought → Action → Observation 循环，每一步的 Observation 结果都会写回消息历史供下一步推理参考，而不是一次性输出。

**我们的实现：**

```
`agent/loop.py` — ReActAgent
Thought: 分析需要查哪些表
Action: search_metadata("肺癌 抗肿瘤药物")
Observation: {"tables": ["dwd.dwd_diagnosis", "dwd.dwd_order", "dim.dim_drug_dict"]}
Action: generate_sql(context)
Observation: {"sql": "SELECT ..."}
Action: validate_sql(sql)
Observation: {"allowed": true}
Action: execute_sql(sql)
Observation: {"rows": [...], "row_count": 15}
Final Answer: "本月肺癌患者抗肿瘤药物费用为 XX 万元..."
```

**与 Hermes 的差异：**
- Hermes 的 ReAct 通常面向通用任务（搜索、代码执行），我们在 Action 层增加了**医疗特定工具**（SQL 安全校验、数据质量检查）
- 增加了**错误类型感知的修复提示**：当 `validate_sql` 失败时，自动向消息流注入结构化中文提示，而不是让模型自行猜测修复方向

---

### 2.2 工具注册与调用（Layer 2）

**借鉴点：** Hermes 将所有外部能力封装为统一接口的工具（Tool），通过 Tool Registry 管理生命周期，支持鉴权、日志和版本控制。

**我们的实现：**

| 工具 | 对应 Hermes 能力 | 医疗特化 |
|------|-----------------|---------|
| `search_metadata` | 知识库检索 | GraphRAG 向量+图混合检索，理解医疗数据血缘 |
| `generate_sql` | 代码生成 | 注入表结构、字段注释、指标口径等医疗上下文 |
| `validate_sql` | 代码检查 | 7条医疗专用安全规则，敏感字段（身份证/手机）拦截 |
| `execute_sql` | 代码执行 | 只读模式，支持 Doris（生产）/ DuckDB（本地）双后端 |
| `analyze_result` | 结果解释 | 结合医疗业务语境生成洞察（如"同比下降可能与新方案替代有关"）|

**与 Hermes 的差异：**
- 增加了 `SqlGuard` 七规则安全层，所有 SQL 必须通过校验才能执行，这是医疗数据隐私合规的强制要求，通用 Agent 框架无此需求

---

### 2.3 记忆层（Layer 3）

**借鉴点：** Hermes 使用持久化记忆（Persistent Memory）保存会话上下文，支持多轮追问而不需要用户重复提供背景信息。

**我们的实现（`agent/memory.py`）：**

```python
# 支持多轮追问
第1轮: "统计本月肺癌患者数量"  → 返回：42人
第2轮: "按科室拆分"           → ConversationMemory 自动注入第1轮上下文
第3轮: "只看住院患者"         → 继续追问，无需重述前两轮
```

技术细节：
- SQLite 存储，按 `session_id` 隔离
- TTL 过期机制（默认 24h），避免历史数据污染新会话
- 前 N 轮注入（默认 5 轮），避免 context 窗口过大

**与 Hermes 的差异：**
- Hermes 记忆层通常存储实体/事实（Episodic Memory），我们存储的是结构化的问-答-SQL 三元组，便于后续 SkillStore 复用

---

### 2.4 技能沉淀层（Layer 4）

**借鉴点：** Hermes 将成功的任务执行链路持久化为"技能"（Skill），相似问题可以直接复用而不必从零推理，这是 Agent 系统区别于普通 RAG 的关键特性。

**我们的实现（两种互补机制）：**

**SkillStore（机器学到的经验）：**
```python
# 执行成功且 confidence >= 0.7 时自动沉淀
skill_store.save_skill(question="肺癌患者本月药费", sql="SELECT ...", tables_used=[...])

# 相似问题到来时检索
similar = skill_store.retrieve_similar("本月肺癌用药金额统计", top_k=3)
# → 返回历史成功案例作为 few-shot 示例
```

**Skills SOP（专家手写的经验）：**
```
skills/anti_tumor_drug_usage.md   # 抗肿瘤药物分析流程
skills/patient_count_analysis.md  # 患者人数统计口径
skills/diagnosis_quality_check.md # 诊断数据 DQ 规则
...（共 8 个）
```

**与 Hermes 的差异：**
- Hermes 技能沉淀通常是通用任务模板，我们增加了**医疗领域 SOP**（Standard Operating Procedure），包含患者去重规则、药品分类方法、诊断编码映射等业务口径
- 技能匹配支持**向量相似度**（`SkillMatcher` + `EmbeddingClient`）和关键词重叠双模式，关键词模式可离线运行

---

### 2.5 任务调度层（Layer 5）

**借鉴点：** Hermes 支持将复杂的多步任务（Multi-step Task）拆解为有依赖关系的子任务 DAG，按拓扑顺序执行，上游结果自动注入下游上下文。

**我们的实现：**

```python
# 复杂问题示例：
"分别统计本月肺癌和乳腺癌患者的药物费用，并对比两者差异"

# TaskPlanner 拆解为：
Task A: "统计本月肺癌患者药物费用"
Task B: "统计本月乳腺癌患者药物费用"  
Task C: "对比 A 和 B 的结果并分析差异"  # depends_on: [A, B]

# TaskScheduler 按依赖顺序执行，A/B 并行，C 等待 A+B 完成
```

复杂度判断：问题包含 ≥2 个关键词（同时/并且/对比/趋势/分别/多个）时路由到 Planner。

**与 Hermes 的差异：**
- 当前实现是串行执行（A → B → C），Hermes 通常支持真正的并行调度
- 依赖注入机制：上游结果通过字符串拼接注入下游 question context，而非共享内存对象

---

## 三、主要设计取舍

### 3.1 为什么不直接用 LangChain？

| 维度 | LangChain | 本项目 |
|------|-----------|--------|
| SQL 安全 | 无内置医疗安全规则 | 7 条规则 + 敏感字段拦截 |
| 元数据 | 通用文档检索 | 医疗 Schema 专用（表口径/字段敏感性/数据血缘） |
| 技能体系 | 无 SOP 机制 | 8 个医疗场景 SOP + SkillStore 自动积累 |
| 可观测性 | 需插件 | 5 张 SQLite 表原生审计（SQL 审计/工具调用链/评测结果） |
| 学习意义 | 黑盒 | 每层设计决策透明，可逐层解释 |

### 3.2 已知局限与改进方向

| 局限 | 当前状态 | 改进方向 |
|------|----------|---------|
| 复杂 JOIN 幻觉 | LLM 生成多表 JOIN 时可能出错 | 增加执行结果行数校验；历史成功 JOIN 模式优先 |
| 意图识别 | 关键词 + 向量双模式 | 接入 Claude Embedding API 提升泛化性 |
| SQL 逻辑正确性 | Jaccard 评估表选择，不评估逻辑 | 引入执行结果与期望结果的对比评估 |
| 任务并行 | 串行执行子任务 | TaskScheduler 升级为 asyncio 并行 |
| 多轮修复 | 最多重试 3 次 + 7 类错误提示 | 按错误类型动态调整 max_steps |

---

## 四、架构演进路线

```
当前状态（原型）
  ↓ 接入真实 Claude Embedding API → Skill 匹配准确率 ↑
  ↓ 引入 Apache Doris 真实连接  → 可在生产数仓跑查询
  ↓ TaskScheduler asyncio 并行  → 多步查询速度 ↑
  ↓ 评测体系接入执行结果校验    → SQL 逻辑正确率可量化
  ↓ 接入 Feishu/WeCom Bot      → 医院数据团队直接使用
```

---

## 五、关键指标总结

| 指标 | 数值 | 说明 |
|------|------|------|
| 核心模块 | 15+ | Agent/SQL/GraphRAG/Storage/Eval |
| 单元测试 | 334+ | 覆盖率含集成测试 |
| Skills SOP | 8 个 | 医疗业务场景标准流程 |
| SQL 安全规则 | 7 条 | 含敏感字段检测 |
| 评测题库 | 30 道 | 覆盖 drug/dq/patient/mpi 等 9 个 domain |
| Session 表 | 5 张 | 全链路 SQLite 审计 |
| 医疗元数据 | 8 张表 | DWD(5) + DWS(1) + ADS(2) |
