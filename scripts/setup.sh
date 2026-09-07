#!/bin/bash
# DeskMate 环境初始化（Step 1 基线）
# 用法: ./scripts/setup.sh
set -e
cd "$(dirname "$0")/.."

echo "🔧 DeskMate 初始化开始"

# 1. Python 虚拟环境与 AI 服务依赖
echo "📦 [1/3] 创建 Python .venv 并安装 ai-service / contracts"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e packages/contracts/py -r services/ai-service/requirements.txt

# 2. Web 主界面（React/Vite）
echo "🌐 [2/3] 安装 apps/web 依赖并构建主界面"
cd apps/web
npm install --silent
npm run build
cd ../..

# 3. 桌面运行时（Tauri）
echo "🖥  [3/3] 安装 apps/desktop 前端依赖（Tauri Rust 构建见下方说明）"
cd apps/desktop
npm install --silent
cd ../..

# 4. 数据目录
mkdir -p data/memory data/run

echo ""
echo "✅ 初始化完成。"
echo ""
echo "下一步："
echo "  # 启动本地 AI 服务（托管主界面 http://127.0.0.1:8736/）"
echo "  ./scripts/dev.sh service"
echo ""
echo "  # 桌面运行时（Tauri，首次需编译 Rust，约 5-15 分钟）"
echo "  cd apps/desktop && npm run tauri dev"
echo ""
echo "  # 运行一致性/接口测试"
echo "  ./scripts/check.sh"
