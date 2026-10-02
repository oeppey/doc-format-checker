#!/usr/bin/env bash
# 启动 doc-format-checker 审查 API（仿 start_app.sh 模式）。
#
# 用法：scripts/start_api.sh [--port PORT]    默认端口 8765
# 外部访问：http://<服务器IP>:<PORT>/  即为完整前端页面（API 自带静态托管，无需 nginx）。
#
# 环境变量均可在外部预设以覆盖默认值（目标服务器部署时按需调整）：
#   CED_MODEL_DIR                          ELECTRA 权重目录
#   DOCUMENT_CHECKER_USE_LLM               1=启用 4B 精检（默认 1）
#   DOCUMENT_CHECKER_CORRECTOR_BASE_URL    精检服务地址（含 /v1）
#   DOCUMENT_CHECKER_CORRECTOR_MODEL       精检模型名
#   DOCUMENT_CHECKER_CORRECTOR_PROTOCOL    corrected_text 或 json
#   DOCUMENT_CHECKER_MAX_REVIEWS           并发审查数
set -uo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$BASE_DIR/logs}"
PORT=8765

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -lt 2 ]] && { echo "Error: --port requires a value"; exit 1; }
      PORT="$2"; shift 2 ;;
    --port=*)
      PORT="${1#*=}"; shift ;;
    -h|--help)
      echo "Usage: $0 [--port PORT]  (default port: 8765)"; exit 0 ;;
    *)
      echo "Unknown argument: $1"; echo "Usage: $0 [--port PORT]  (default port: 8765)"; exit 1 ;;
  esac
done
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 ]] || [[ "$PORT" -gt 65535 ]]; then
  echo "Invalid port: ${PORT} (must be an integer in 1-65535)"; exit 1
fi

# ---- 环境配置（外部预设优先） ----
export CED_MODEL_DIR="${CED_MODEL_DIR:-$BASE_DIR/data/models/ChineseErrorDetectorElectra}"
export DOCUMENT_CHECKER_USE_LLM="${DOCUMENT_CHECKER_USE_LLM:-1}"
export DOCUMENT_CHECKER_CORRECTOR_BASE_URL="${DOCUMENT_CHECKER_CORRECTOR_BASE_URL:-http://127.0.0.1:8000/v1}"
export DOCUMENT_CHECKER_CORRECTOR_MODEL="${DOCUMENT_CHECKER_CORRECTOR_MODEL:-twnlp/ChineseErrorCorrector4-4B}"
export DOCUMENT_CHECKER_CORRECTOR_PROTOCOL="${DOCUMENT_CHECKER_CORRECTOR_PROTOCOL:-corrected_text}"
export DOCUMENT_CHECKER_MAX_REVIEWS="${DOCUMENT_CHECKER_MAX_REVIEWS:-1}"

PY="$BASE_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "错误：未找到 $PY（请先在仓库根创建 .venv 并安装依赖）"; exit 1; }
[[ -d "$CED_MODEL_DIR" ]] || \
  echo "警告：ELECTRA 权重目录不存在：$CED_MODEL_DIR（错字检查将降级为「未检查」，其余功能可用）"

mkdir -p "$LOG_DIR"
cd "$BASE_DIR"

# ---- 清理占用端口的旧进程 ----
OLD_PIDS="$(lsof -t -i:"$PORT" 2>/dev/null || fuser "$PORT/tcp" 2>/dev/null || true)"
if [[ -n "$OLD_PIDS" ]]; then
  echo "Port ${PORT} is in use by PID(s): ${OLD_PIDS}, killing..."
  kill $OLD_PIDS 2>/dev/null || true
  sleep 2
  STILL_ALIVE="$(lsof -t -i:"$PORT" 2>/dev/null || fuser "$PORT/tcp" 2>/dev/null || true)"
  if [[ -n "$STILL_ALIVE" ]]; then
    echo "Force killing: ${STILL_ALIVE}"
    kill -9 $STILL_ALIVE 2>/dev/null || true
    sleep 1
  fi
  echo "Old process on port ${PORT} terminated."
else
  echo "Port ${PORT} is free."
fi

# ---- 启动 ----
echo "===== [$(date '+%Y-%m-%d %H:%M:%S')] starting api on port ${PORT} =====" >> "$LOG_DIR/api.log"
nohup "$PY" -m uvicorn document_checker.api:app \
  --host 0.0.0.0 --port "$PORT" \
  >> "$LOG_DIR/api.log" 2>&1 &
APP_PID=$!
echo "$APP_PID" > "$LOG_DIR/api.pid"

# ---- 健康检查（最多等 30 秒） ----
for _ in $(seq 1 30); do
  sleep 1
  if curl -s -o /dev/null -m 2 "http://127.0.0.1:${PORT}/api/catalog"; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "API 已启动（PID ${APP_PID}）"
    echo "本机访问: http://127.0.0.1:${PORT}/"
    [[ -n "${IP:-}" ]] && echo "外部访问: http://${IP}:${PORT}/"
    echo "日志: $LOG_DIR/api.log"
    exit 0
  fi
done
echo "启动失败：健康检查 30 秒内未通过，日志尾部如下："
tail -20 "$LOG_DIR/api.log"
exit 1
