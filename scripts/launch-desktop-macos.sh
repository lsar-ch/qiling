#!/bin/bash
# macOS 桌面入口：清理残留后在后台启动 Tauri 开发运行时。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/data/run"
LOG="$RUN_DIR/desktop.log"
mkdir -p "$RUN_DIR"

exec >>"$LOG" 2>&1
echo
echo "=== DeskMate desktop launch $(date '+%Y-%m-%d %H:%M:%S') ==="

export PATH="/Users/lxb/.local/bin:/Users/lxb/.cargo/bin:/opt/homebrew/bin:$PATH"
export DESKMATE_HOME="$ROOT"

pkill -f 'target/debug/deskmate-desktop' 2>/dev/null || true
pkill -f "$ROOT/.venv/bin/python -m uvicorn app.main:app" 2>/dev/null || true

for port in 1420 8736; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -n "$pids" ] && kill $pids 2>/dev/null || true
done

for _ in {1..20}; do
  if ! lsof -tiTCP:1420 -sTCP:LISTEN >/dev/null 2>&1 &&
     ! lsof -tiTCP:8736 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

for port in 1420 8736; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
done

echo $$ >"$RUN_DIR/desktop.pid"
cd "$ROOT/apps/desktop" || exit 1
echo "Starting: npm run tauri dev"
exec npm run tauri dev
