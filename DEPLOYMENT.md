# ai-data-agent Linux 部署指南

## 架构总览

```
┌─────────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────────┐
│  用户请求     │────▶│ FastAPI   │────▶│ Milvus   │     │ 阿里云 DashScope │
│  HTTP/JSON  │     │ :8000    │     │ :19530   │     │ LLM + Embedding  │
└─────────────┘     └────┬─────┘     └──────────┘     └──────────────────┘
                         │
                         ▼
                   ┌──────────┐
                   │  Doris   │
                   │ :9030    │
                   └──────────┘
```

| 组件 | 用途 | 部署方式 |
|------|------|---------|
| Doris | SQL 查询引擎 | Docker 或本机安装 |
| Milvus | 向量检索 | Docker |
| ai-data-agent | 主服务 | Docker 或 Conda + systemd |
| LLM / Embedding | 阿里云 DashScope | 云服务，无需安装 |

---

## 方式一：Docker Compose 全栈部署（推荐）

一条命令启动所有服务。

### 1. 环境准备

```bash
# 安装 Docker 和 Docker Compose
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效

# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 验证
docker --version
docker-compose --version
```

### 2. 准备配置文件

```bash
cd ai-data-agent

# 创建 .env 文件（填入你的 DashScope API Key）
cat > .env << 'EOF'
LLM_API_KEY=sk-你的DashScope密钥
EMBEDDING_API_KEY=sk-你的DashScope密钥
EOF
```

### 3. 一键启动

```bash
docker-compose up -d
```

启动的服务：

| 容器 | 端口 | 说明 |
|------|------|------|
| `doris-fe` | 8030, 9030 | Doris Frontend |
| `doris-be` | 8040 | Doris Backend |
| `doris-init` | - | 自动建库建表（执行完退出） |
| `milvus` | 19530, 9091 | 向量数据库 |
| `etcd` | 2379 | Milvus 依赖 |
| `minio` | 9000, 9001 | Milvus 依赖 |
| `ai-data-agent` | 8000 | 主服务 API |

### 4. 初始化元数据

```bash
# 等待所有服务就绪（约 1-2 分钟）
docker-compose ps

# 进入 ai-data-agent 容器执行元数据入库
docker-compose exec ai-data-agent \
  conda run --no-capture-output -n ai-data-agent \
  ai-data-agent ingest-metadata \
    --config config/application.local.yaml \
    --metadata-root metadata \
    --create-collection
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/health
curl http://localhost:8000/health/ready

# Agent 查询测试
curl -X POST http://localhost:8000/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"question": "各科室药品使用量排名前10"}'
```

### 6. 常用命令

```bash
# 查看日志
docker-compose logs -f ai-data-agent
docker-compose logs -f doris-fe

# 重启服务
docker-compose restart ai-data-agent

# 停止所有服务
docker-compose down

# 停止并清除数据
docker-compose down -v

# 重新构建镜像（代码变更后）
docker-compose build ai-data-agent
docker-compose up -d ai-data-agent
```

---

## 方式二：Conda 手动部署

不用 Docker，直接在服务器上用 Conda 管理 Python 环境。

### 1. 安装 Conda

```bash
# 下载 Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3

# 初始化 shell
$HOME/miniconda3/bin/conda init bash
source ~/.bashrc

# 验证
conda --version
```

### 2. 安装 Doris

```bash
# 下载
sudo mkdir -p /opt/doris && cd /opt/doris
DORIS_VERSION="2.1.7"
wget "https://apache-doris-releases.oss-cn-beijing.aliyuncs.com/apache-doris-${DORIS_VERSION}-bin-x86_64.tar.xz"
tar -xvf "apache-doris-${DORIS_VERSION}-bin-x86_64.tar.xz"
mv "apache-doris-${DORIS_VERSION}-bin-x86_64" doris

# 配置 FE
sudo mkdir -p /data/doris/fe /data/doris/be
cat > /opt/doris/doris/fe/conf/fe.conf << 'EOF'
http_port = 8030
rpc_port = 9020
query_port = 9030
edit_log_port = 9010
meta_dir = /data/doris/fe
JAVA_OPTS = "-Xmx4096m"
priority_networks = 0.0.0.0/0
EOF

# 配置 BE
cat > /opt/doris/doris/be/conf/be.conf << 'EOF'
webserver_port = 8040
heartbeat_service_port = 9050
brpc_port = 8060
storage_root_path = /data/doris/be
JAVA_OPTS = "-Xmx2048m"
priority_networks = 0.0.0.0/0
EOF

# 启动
/opt/doris/doris/fe/bin/start_fe.sh --daemon
/opt/doris/doris/be/bin/start_be.sh --daemon

# 注册 BE
sleep 5
mysql -h 127.0.0.1 -P 9030 -u root -e "ALTER SYSTEM ADD BACKEND '127.0.0.1:9050';"
sleep 30

# 验证
mysql -h 127.0.0.1 -P 9030 -u root -e "SHOW BACKENDS\G"

# 建库建表
mysql -h 127.0.0.1 -P 9030 -u root << 'SQL'
CREATE DATABASE IF NOT EXISTS gmall;
CREATE DATABASE IF NOT EXISTS dq;
USE gmall;
CREATE TABLE IF NOT EXISTS dws_drug_usage_1d (
    stat_date DATE COMMENT "统计日期",
    dept_name VARCHAR(100) COMMENT "科室名称",
    drug_name VARCHAR(200) COMMENT "药品名称",
    usage_amount DECIMAL(18,4) COMMENT "使用量",
    usage_cost DECIMAL(18,2) COMMENT "使用金额",
    patient_count INT COMMENT "患者数"
) ENGINE=OLAP
DUPLICATE KEY(stat_date, dept_name, drug_name)
DISTRIBUTED BY HASH(stat_date) BUCKETS 4
PROPERTIES("replication_num" = "1");

USE dq;
CREATE TABLE IF NOT EXISTS ai_data_agent_audit_log (
    request_id VARCHAR(64), question VARCHAR(1000), sql_text TEXT,
    status VARCHAR(32), retrieved_sources INT, context_tables VARCHAR(500),
    context_metrics VARCHAR(500), context_dq_rules VARCHAR(500),
    row_count INT, elapsed_ms INT, error_message VARCHAR(1000),
    answer_summary TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(request_id)
DISTRIBUTED BY HASH(request_id) BUCKETS 2
PROPERTIES("replication_num" = "1");
SQL
```

### 3. 安装 Milvus（Docker）

```bash
sudo mkdir -p /opt/milvus && cd /opt/milvus
wget https://github.com/milvus-io/milvus/releases/download/v2.4.17/milvus-standalone-docker-compose.yml \
  -O docker-compose.yml
docker-compose up -d

# 验证
curl http://localhost:19530/healthz
```

### 4. 创建 Conda 环境并安装应用

```bash
cd ai-data-agent

# 创建 conda 环境
conda env create -f environment.yml
conda activate ai-data-agent

# 安装应用（开发模式）
pip install -e ".[test]"
```

### 5. 配置

```bash
# .env 文件
cat > .env << 'EOF'
DORIS_HOST=127.0.0.1
DORIS_PORT=9030
DORIS_USER=root
DORIS_PASSWORD=
DORIS_DATABASE=gmall

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION=medical_metadata

LLM_PROVIDER=openai
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY=sk-你的DashScope密钥

EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=sk-你的DashScope密钥
EMBEDDING_DIMENSION=1024
EOF
```

### 6. 初始化元数据并启动

```bash
conda activate ai-data-agent

# 元数据入库
ai-data-agent ingest-metadata \
  --config config/application.local.yaml \
  --metadata-root metadata \
  --create-collection

# 运行测试
python -m pytest tests -v

# 启动服务
ai-data-agent serve \
  --config config/application.local.yaml \
  --metadata-root metadata \
  --host 0.0.0.0 --port 8000
```

### 7. systemd 服务（生产推荐）

```bash
CONDA_ENV=ai-data-agent
APP_PATH=$(pwd)

sudo tee /etc/systemd/system/ai-data-agent.service > /dev/null << EOF
[Unit]
Description=Medical Data Agent API
After=network.target
Wants=milvus.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${APP_PATH}
Environment=CONDA_DEFAULT_ENV=${CONDA_ENV}
EnvironmentFile=${APP_PATH}/.env
ExecStart=${HOME}/miniconda3/envs/${CONDA_ENV}/bin/python -m ai_data_agent.cli serve \\
  --config ${APP_PATH}/config/application.local.yaml \\
  --metadata-root ${APP_PATH}/metadata \\
  --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ai-data-agent
sudo systemctl start ai-data-agent

# 查看日志
sudo journalctl -u ai-data-agent -f
```

---

## 阿里云 DashScope 配置

LLM 和 Embedding 均使用 OpenAI 兼容 API。

### 开通步骤

1. 登录 [阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 开通服务
3. 在「API-KEY 管理」创建 Key

### 推荐模型

| 用途 | 模型 | 说明 |
|------|------|------|
| SQL 生成 + Agent | `qwen-plus` | 性价比高，支持 function calling |
| Embedding | `text-embedding-v3` | 1024 维，中文效果好 |

备选：`qwen-max`（最强）、`qwen-turbo`（最快）

### API 地址

```
https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 测试 API Key

```bash
curl https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Authorization: Bearer sk-你的密钥" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen-plus","messages":[{"role":"user","content":"hello"}]}'
```

---

## 验证部署

```bash
# 健康检查
curl http://localhost:8000/health
curl http://localhost:8000/health/ready

# 传统查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "各科室药品使用量排名前10"}'

# Agent 模式查询（有推理步骤）
curl -X POST http://localhost:8000/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"question": "各科室药品使用量排名前10"}'

# 评测
ai-data-agent evaluate --config config/application.local.yaml --dry-run
```

---

## 常见问题

### Doris BE 无法启动

```bash
# 系统参数
echo "vm.max_map_count = 262144" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# 查看日志
tail -100 /opt/doris/doris/be/log/be.INFO
```

### Milvus 连接失败

```bash
docker ps | grep milvus
docker-compose -f /opt/milvus/docker-compose.yml restart
```

### DashScope 报错

- `401` → API Key 无效
- `429` → 限流，稍后重试
- `400` → 模型名错误

### Embedding 维度不匹配

```bash
# 删除旧 collection 重建
python3 -c "
from pymilvus import connections, utility
connections.connect(host='localhost', port=19530)
if utility.has_collection('medical_metadata'):
    utility.drop_collection('medical_metadata')
connections.disconnect('default')
"
ai-data-agent ingest-metadata --config config/application.local.yaml --metadata-root metadata --create-collection
```

---

## 端口汇总

| 端口 | 服务 |
|------|------|
| 8000 | ai-data-agent API |
| 9030 | Doris FE（MySQL 协议） |
| 8030 | Doris FE（HTTP） |
| 19530 | Milvus |

## 资源估算

| 场景 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| 最低（测试） | 4 核 | 8 GB | 50 GB |
| 推荐（生产） | 10 核 | 16 GB | 80 GB |
