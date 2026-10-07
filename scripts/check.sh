#!/bin/bash
# 栖灵 快速检查：契约一致性 + 接口测试 + 前端类型检查
cd "$(dirname "$0")/.."
set -e

echo "── Python 测试（contracts 一致性 + ai-service 接口）"
cd services/ai-service
../../.venv/bin/python -m pytest -q

echo "── Web 类型检查"
cd ../../apps/web
npm run typecheck --silent

echo "── Desktop 类型检查"
cd ../desktop
npm run typecheck --silent

echo "── Desktop 单元测试（vitest）"
npm run test --silent

echo "✅ 全部通过"
