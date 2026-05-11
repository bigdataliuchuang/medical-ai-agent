#!/usr/bin/env bash
# Pocket Demo 一键启动脚本：
# 1. 初始化本地 DuckDB 示例数仓
# 2. 按需构建 Milvus Lite 元数据索引
# 3. 启动 Medical Data Agent Web/API 服务
set -euo pipefail

# 切换到 ai-data-agent 项目根目录，保证后续相对路径稳定可用。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 可通过环境变量覆盖默认配置，例如：
#   PORT=8010 REBUILD_METADATA=1 bash scripts/run_pocket_demo.sh
CONDA_ENV="${CONDA_ENV:-ai-data-agent}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
CONFIG="${CONFIG:-config/application.pocket.yaml}"
METADATA_ROOT="${METADATA_ROOT:-metadata}"

# 本地 Pocket Demo 依赖 .env 中的模型/API Key 等敏感配置。
if [[ ! -f ".env" ]]; then
  echo "Missing .env. Create it from .env.pocket.example and fill API keys." >&2
  echo "  cp .env.pocket.example .env" >&2
  exit 1
fi

# Milvus Lite 使用本地文件数据库；同一时间只能由一个进程打开。
# 如果上一次服务被 Ctrl+Z 挂起，数据库文件可能仍被旧进程占用。
if command -v lsof >/dev/null 2>&1 && lsof data/medical_metadata.db >/dev/null 2>&1; then
  echo "Milvus Lite metadata is already opened by another process:" >&2
  lsof data/medical_metadata.db >&2
  echo "" >&2
  echo "Stop the old service first. If it was suspended with Ctrl+Z, run:" >&2
  echo "  jobs" >&2
  echo "  kill %<job-number>" >&2
  echo "or stop the listed PID with:" >&2
  echo "  kill <pid>" >&2
  exit 1
fi

echo "[1/3] Initializing local DuckDB warehouse..."
# 创建或刷新本地 DuckDB 示例数据，供 Text2SQL 查询执行使用。
conda run -n "$CONDA_ENV" python scripts/init_pocket_duckdb.py

# 首次运行或显式设置 REBUILD_METADATA=1 时，重建 Milvus Lite 向量索引。
# 已存在索引时直接复用，可缩短二次启动时间。
if [[ "${REBUILD_METADATA:-0}" == "1" || ! -f "data/medical_metadata.db" ]]; then
  echo "[2/3] Rebuilding Milvus Lite metadata..."
  # 清理旧数据库和锁文件，避免残留状态影响重建。
  rm -f data/medical_metadata.db data/medical_metadata.db.lock data/.medical_metadata.db.lock
  conda run -n "$CONDA_ENV" ai-data-agent ingest-metadata \
    --config "$CONFIG" \
    --metadata-root "$METADATA_ROOT" \
    --create-collection
else
  echo "[2/3] Milvus Lite metadata already exists. Set REBUILD_METADATA=1 to rebuild."
fi

echo "[3/3] Starting Medical Data Agent at http://${HOST}:${PORT}"
echo "Open http://${HOST}:${PORT}/ in your browser."
# 使用 exec 让当前 shell 进程交给服务进程，便于 Ctrl+C 直接停止服务。
exec conda run --no-capture-output -n "$CONDA_ENV" ai-data-agent serve \
  --config "$CONFIG" \
  --metadata-root "$METADATA_ROOT" \
  --host "$HOST" \
  --port "$PORT"
