#!/bin/bash
# DeskMate 开发启动器
# 用法:
#   ./scripts/dev.sh service   # 只启动本地 AI 服务（默认）
#   ./scripts/dev.sh web       # 前端 Vite 开发模式（HMR，端口 5173）
#   ./scripts/dev.sh all       # 服务 + 前端
cd "$(dirname "$0")/.."
set -e

MODE="${1:-service}"

start_service() {
  echo "🚀 AI 服务: http://127.0.0.1:8736/ (主界面 + /api)"
  cd services/ai-service
  exec ../../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8736 --reload
}

start_web() {
  echo "🌐 Web dev: http://localhost:5173/"
  cd apps/web
  exec npm run dev
}

case "$MODE" in
  service) start_service ;;
  web) start_web ;;
  all)
    start_web &
    WEB_PID=$!
    trap 'kill $WEB_PID 2>/dev/null' EXIT
    start_service
    ;;
  *) echo "未知模式: $MODE（可用 service | web | all）"; exit 1 ;;
esac
