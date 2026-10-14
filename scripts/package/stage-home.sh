#!/bin/bash
# 组装随包分发的只读 home 模板：Rust 首启时整体拷到 Application Support。
# 用法：scripts/package/stage-home.sh <输出目录>
set -eu

OUT="${1:?usage: stage-home.sh <output-dir>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ ! -d "$ROOT/apps/web/dist" ]; then
  echo "缺少 apps/web/dist，请先 npm run build" >&2
  exit 1
fi

mkdir -p "$OUT"

# 配置：agents.local.yaml 是用户运行时覆盖层，不随包分发
mkdir -p "$OUT/config"
rsync -a --exclude 'agents.local.yaml' "$ROOT/config/" "$OUT/config/"

# 主界面构建产物
mkdir -p "$OUT/apps/web"
rsync -a "$ROOT/apps/web/dist" "$OUT/apps/web/"

# 只随包分发当前三个角色卡对应的资产（其余为历史试验/第三方残留）
mkdir -p "$OUT/data/persona-assets"
for id in default persona_2 qiling; do
  rsync -a "$ROOT/data/persona-assets/$id" "$OUT/data/persona-assets/"
done

mkdir -p "$OUT/data/run"
grep -m1 'version:' "$ROOT/config/settings.yaml" | awk '{print $2}' > "$OUT/.seed-version"

du -sh "$OUT"
