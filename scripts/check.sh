#!/bin/bash
# 栖灵 快速检查：契约一致性 + 接口测试 + 前端类型检查
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -euo pipefail

if [ -x "$ROOT/.venv/bin/python" ]; then
  VENV_PY="$ROOT/.venv/bin/python"
elif [ -f "$ROOT/.venv/Scripts/python.exe" ]; then
  VENV_PY="$ROOT/.venv/Scripts/python.exe"
else
  echo "缺少 .venv Python：请先运行 scripts/setup.sh，或按 Windows 文档创建 .venv" >&2
  exit 1
fi

echo "── Python 测试（contracts 一致性 + ai-service 接口）"
cd services/ai-service
"$VENV_PY" -m pytest -q

echo "── Web 类型检查"
cd ../../apps/web
npm run typecheck --silent

echo "── Desktop 类型检查"
cd ../desktop
npm run typecheck --silent

echo "── Desktop 单元测试（vitest）"
npm run test --silent

echo "✅ 全部通过"
