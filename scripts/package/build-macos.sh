#!/bin/bash
# 出 macOS 安装包：冻结 sidecar + home 模板 + Tauri universal（本机先按单架构验证）。
# 用法：scripts/package/build-macos.sh [x86_64|aarch64|universal]
set -eu

ARCH="${1:-$(uname -m)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$ROOT/apps/desktop/src-tauri/resources"

echo "== 1/4 主界面构建"
(cd "$ROOT/apps/web" && npm run build)

echo "== 2/4 冻结 ai-service（PyInstaller onedir）"
( "$ROOT/.venv/bin/pyinstaller" --version >/dev/null 2>&1 ) || \
  "$ROOT/.venv/bin/pip" install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
(cd "$ROOT/services/ai-service" &&
  "$ROOT/.venv/bin/pyinstaller" ai-service.spec --noconfirm \
    --distpath "$ROOT/build/sidecar/dist" --workpath "$ROOT/build/sidecar/work")

echo "== 3/4 组装 src-tauri/resources"
mkdir -p "$RES/runtime"
rm -rf "$RES/runtime/ai-service" "$RES/home-template"
cp -R "$ROOT/build/sidecar/dist/ai-service" "$RES/runtime/ai-service"
"$ROOT/scripts/package/stage-home.sh" "$RES/home-template"

echo "== 4/4 Tauri 构建"
TARGET_ARGS=()
case "$ARCH" in
  x86_64) TARGET_ARGS=(-- --target x86_64-apple-darwin) ;;
  aarch64) TARGET_ARGS=(-- --target aarch64-apple-darwin) ;;
  universal) TARGET_ARGS=(-- --target universal-apple-darwin) ;;
esac
(cd "$ROOT/apps/desktop" &&
  MACOSX_DEPLOYMENT_TARGET=12.0 npm run tauri build --config src-tauri/tauri.release.json "${TARGET_ARGS[@]}")

echo "完成：$ROOT/apps/desktop/src-tauri/target/${ARCH}/release/bundle"
