#!/bin/bash
# 栖灵 一键安装脚本（P2-T1）
# 用法:
#   ./scripts/setup.sh                  # 基础安装：工具链检测 + .venv + 前端依赖/构建 + smoke test
#   ./scripts/setup.sh --with-voice     # 追加本地语音依赖（麦克风采集 + VAD）
#   ./scripts/setup.sh --with-browser   # 追加 Playwright Chromium（浏览器执行器）
#   ./scripts/setup.sh --help           # 查看用法
# 平台：macOS / Linux。Windows 请按 docs/WINDOWS-MIGRATION-2026-09.md 手动安装。
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
SMOKE_PORT="${SMOKE_PORT:-8799}"
SMOKE_LOG="data/run/setup-smoke.log"
WITH_VOICE=0
WITH_BROWSER=0
OPTIONAL_FAILED=0
SMOKE_PID=""

# ── 输出与失败处理 ────────────────────────────────────────────
say()  { printf '%s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*"; }

usage() {
  cat <<'EOF'
栖灵 安装脚本（macOS / Linux）

用法：
  ./scripts/setup.sh [--with-voice] [--with-browser]

选项：
  --with-voice    追加本地语音依赖（sounddevice / numpy / webrtcvad）；
                  默认的云端语音链路只需 API key，不需要这些包
  --with-browser  追加 Playwright Chromium 浏览器二进制（浏览器执行器需要）
  -h, --help      显示本帮助

环境变量：
  PYTHON      指定 Python 解释器（默认自动探测 3.11+）
  SMOKE_PORT  smoke test 使用的端口（默认 8799，避开开发端口 8736）
EOF
}

print_fix_entry() {
  cat <<EOF

修复入口：
  1) 工具链缺失：按上方提示安装（macOS: brew install ...；Debian/Ubuntu: sudo apt-get install ...）
  2) Python 依赖失败：手动重跑
       .venv/bin/python -m pip install -e packages/contracts/py -r services/ai-service/requirements.txt
  3) npm ci 失败：多为 package-lock.json 与 package.json 不同步，进入 apps/web 或 apps/desktop
     执行 npm install 后重新提交 lock，再重跑本脚本
  4) smoke test 失败：看 $SMOKE_LOG 末尾日志；端口被占用时用 SMOKE_PORT=8811 ./scripts/setup.sh 重跑
  5) 文档：README.md、docs/HANDOVER-2026-09-13.md、docs/PROJECT-ROADMAP.md
EOF
}

die() { printf '\n❌ %s\n' "$*" >&2; print_fix_entry >&2; exit 1; }

on_error() {
  printf '\n❌ 安装中断：命令 `%s` 失败（退出码 %s，脚本第 %s 行）\n' \
    "${BASH_COMMAND%%$'\n'*}" "$1" "$2" >&2
  print_fix_entry >&2
  exit "$1"
}
trap 'on_error $? $LINENO' ERR

cleanup() {
  if [ -n "$SMOKE_PID" ]; then
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
    SMOKE_PID=""
  fi
}
trap cleanup EXIT

fetch_health() {  # 打印 /api/health 响应体片段；HTTP 200 返回 0，其余返回 1
  # 轮询期间的失败是预期的，用 || return 1 避免触发 ERR trap
  "$VENV_PY" - "$1" <<'PY' || return 1
import sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:%s/api/health" % sys.argv[1], timeout=8) as r:
        sys.stdout.write(r.read().decode("utf-8", "replace")[:300])
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

# ── 参数解析 ─────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --with-voice)   WITH_VOICE=1 ;;
    --with-browser) WITH_BROWSER=1 ;;
    -h|--help)      usage; exit 0 ;;
    *)              usage >&2; die "未知参数：$1" ;;
  esac
  shift
done

# ── 平台判断 ─────────────────────────────────────────────────
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin) OS_NAME="macos" ;;
  Linux)  OS_NAME="linux" ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    cat <<'EOF'
❌ 检测到 Windows 环境：本脚本只支持 macOS / Linux，不做任何改动。
   请按 docs/WINDOWS-MIGRATION-2026-09.md 在 PowerShell 中手动安装，关键步骤：
     python -m venv .venv
     .venv\Scripts\python.exe -m pip install -e packages\contracts\py -r services\ai-service\requirements.txt
     cd apps\web; npm ci; npm run build; cd ..\desktop; npm ci
EOF
    exit 1 ;;
  *) OS_NAME="unknown"; warn "未识别的系统：$(uname -s 2>/dev/null || echo unknown)，按 Linux 方式给出安装提示" ;;
esac

pkg_hint() {  # $1=macOS 命令 $2=Linux 命令
  if [ "$OS_NAME" = "macos" ]; then say "      macOS: $1"; else say "      Linux: $2"; fi
}

# 变量后紧跟全角字符时必须加花括号：bash 在部分 locale 下会把高位字节并入变量名
say "🔧 栖灵 安装开始（系统：${OS_NAME}，目录：${ROOT}）"

# ── 1. 工具链检测 ────────────────────────────────────────────
say ""
say "🧭 [1/6] 检查工具链（Python 3.11+ / Node 20+ / Rust）"

PY_OK='import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
PYTHON_BIN="${PYTHON:-}"
if [ -n "$PYTHON_BIN" ]; then
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "PYTHON=$PYTHON_BIN 不存在或不可执行"
  "$PYTHON_BIN" -c "$PY_OK" 2>/dev/null || die "PYTHON=$PYTHON_BIN 版本低于 3.11：$("$PYTHON_BIN" -V 2>&1)"
else
  for candidate in python3 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "$PY_OK" 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  say "❌ 未找到 Python 3.11+"
  pkg_hint "brew install python@3.12" \
           "sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv"
  die "请先安装 Python 3.11+，或用 PYTHON=/path/to/python3.12 ./scripts/setup.sh 指定解释器"
fi
say "  ✓ Python: $("$PYTHON_BIN" -V 2>&1)（${PYTHON_BIN}）"

if ! command -v node >/dev/null 2>&1; then
  say "❌ 未找到 Node.js"
  pkg_hint "brew install node@20 && brew link --overwrite node@20" \
           "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
  die "请先安装 Node 20+（含 npm）"
fi
node -e 'process.exit(parseInt(process.versions.node, 10) >= 20 ? 0 : 1)' \
  || die "Node 版本过低：$(node -v)，需要 20+"
command -v npm >/dev/null 2>&1 || die "已找到 node 但缺少 npm，请重装 Node 20+"
say "  ✓ Node: $(node -v) / npm $(npm -v)"

if command -v cargo >/dev/null 2>&1 && command -v rustc >/dev/null 2>&1; then
  say "  ✓ Rust: $(cargo --version 2>&1) / $(rustc --version 2>&1)"
else
  warn "未检测到 Rust（cargo/rustc）——只在构建 Tauri 桌面端时才需要，本脚本可继续"
  say "      安装：curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh（重开终端生效）"
  if [ "$OS_NAME" != "macos" ]; then
    say "      Linux 桌面端还需系统库：sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential libssl-dev libasound2-dev librsvg2-dev"
  fi
fi

# ── 2. Python 虚拟环境与依赖 ─────────────────────────────────
say ""
say "📦 [2/6] Python .venv 与 ai-service / contracts 依赖"
if [ -d .venv ]; then
  [ -x "$VENV_PY" ] || die ".venv 已存在但不可用（缺少 .venv/bin/python）。修复：rm -rf .venv 后重跑 ./scripts/setup.sh"
  say "  ✓ 复用已有 .venv"
else
  "$PYTHON_BIN" -m venv .venv \
    || die "创建 .venv 失败。Debian/Ubuntu 通常缺 venv 模块：sudo apt-get install -y python3-venv"
  say "  ✓ 已用 $PYTHON_BIN 创建 .venv"
fi
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -e packages/contracts/py -r services/ai-service/requirements.txt
say "  ✓ Python 依赖安装完成"

# ── 3. Web 主界面 ────────────────────────────────────────────
say ""
say "🌐 [3/6] apps/web 依赖（npm ci）与主界面构建"
cd "$ROOT/apps/web"
npm ci --silent --no-audit --no-fund
npm run build
cd "$ROOT"
say "  ✓ apps/web 构建完成（ai-service 托管 apps/web/dist）"

# ── 4. 桌面运行时前端依赖 ────────────────────────────────────
say ""
say "🖥  [4/6] apps/desktop 依赖（npm ci；Tauri Rust 构建见结尾说明）"
cd "$ROOT/apps/desktop"
npm ci --silent --no-audit --no-fund
cd "$ROOT"
say "  ✓ apps/desktop 依赖安装完成"

# ── 5. 数据目录与可选组件 ────────────────────────────────────
say ""
say "🧩 [5/6] 数据目录与可选组件"
mkdir -p data/memory data/run
say "  ✓ data/memory、data/run"

if [ "$WITH_VOICE" -eq 1 ]; then
  say "  → --with-voice：安装本地语音依赖（麦克风采集 + 端点检测）"
  # ponytail: 云端 STT/TTS（dashscope/minimax）已在基础 requirements 里，这里只补本地录音/VAD；
  #           需要离线识别时再手动 pip install faster-whisper（体积大，默认不装）
  # 不加 --quiet：装失败时要能看到 pip 的真实报错
  if "$VENV_PY" -m pip install sounddevice numpy webrtcvad; then
    say "    ✓ sounddevice / numpy / webrtcvad"
  else
    OPTIONAL_FAILED=1
    warn "本地语音依赖安装失败（基础语音链路不受影响）"
    pkg_hint "brew install portaudio" \
             "sudo apt-get install -y portaudio19-dev libasound2-dev python3-dev build-essential"
    say "      重试：.venv/bin/python -m pip install sounddevice numpy webrtcvad"
  fi
  # key 可以来自环境变量，也可以来自项目根 .env（app/config.py 用 dotenv 自动加载）
  VOICE_KEY_FOUND=0
  if [ -n "${DASHSCOPE_API_KEY:-}" ] || [ -n "${MINIMAX_API_KEY:-}" ]; then
    VOICE_KEY_FOUND=1
  elif [ -f .env ] && grep -Eq '^[[:space:]]*(DASHSCOPE_API_KEY|MINIMAX_API_KEY)=[^[:space:]]' .env; then
    VOICE_KEY_FOUND=1
  fi
  if [ "$VOICE_KEY_FOUND" -ne 1 ]; then
    warn "未检测到 DASHSCOPE_API_KEY / MINIMAX_API_KEY（环境变量与 .env 均无）：语音会降级为不可用"
    say "      配置入口：项目根 .env，或 config/settings.yaml 的 voice 段；详见 docs/VOICE-PROVIDERS.md"
  fi
else
  say "  · 未指定 --with-voice，跳过本地语音依赖"
fi

if [ "$WITH_BROWSER" -eq 1 ]; then
  say "  → --with-browser：安装 Playwright Chromium（浏览器执行器）"
  if "$VENV_PY" -m playwright install chromium; then
    say "    ✓ Chromium 就绪"
  else
    OPTIONAL_FAILED=1
    warn "Playwright Chromium 安装失败"
    say "      Linux 缺系统库时执行：sudo $VENV_PY -m playwright install-deps chromium"
    say "      手动重试：.venv/bin/python -m playwright install chromium"
  fi
else
  say "  · 未指定 --with-browser，跳过 Chromium 下载"
fi

# ── 6. smoke test ────────────────────────────────────────────
say ""
say "🩺 [6/6] smoke test：启动 ai-service → 等待 /api/health 200 → 关闭"
: > "$SMOKE_LOG"
cd "$ROOT/services/ai-service"
"$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$SMOKE_PORT" \
  > "$ROOT/$SMOKE_LOG" 2>&1 &
SMOKE_PID=$!
cd "$ROOT"

HEALTH_OK=0
HEALTH_BODY=""
# 轮询期间的非零返回是预期行为；set -E 会把 ERR trap 带进命令替换的子 shell，
# 所以这里临时摘掉 trap，否则冷启动等待会重复打印「安装中断」横幅。
trap - ERR
for _ in $(seq 1 45); do
  if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
    break
  fi
  if HEALTH_BODY="$(fetch_health "$SMOKE_PORT")"; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done
trap 'on_error $? $LINENO' ERR

if [ "$HEALTH_OK" -ne 1 ]; then
  say "──── $SMOKE_LOG 末尾 40 行 ────"
  tail -n 40 "$SMOKE_LOG" 2>/dev/null || true
  cleanup
  die "ai-service 未在 45 秒内让 /api/health 返回 200（端口 ${SMOKE_PORT}，完整日志：${SMOKE_LOG}）"
fi
say "  ✓ /api/health 200：$(printf '%s' "$HEALTH_BODY" | head -c 200)"
cleanup
say "  ✓ smoke 服务已关闭"

# ── 结尾 ─────────────────────────────────────────────────────
say ""
if [ "$OPTIONAL_FAILED" -eq 1 ]; then
  warn "基础安装已完成，但有可选组件没装好（见上方 ⚠️）"
else
  say "✅ 安装完成。"
fi
say ""
say "下一步："
say "  # 启动本地 AI 服务（托管主界面 http://127.0.0.1:8736/）"
say "  ./scripts/dev.sh service"
say ""
say "  # 桌面运行时（Tauri，首次需编译 Rust，约 5-15 分钟）"
say "  cd apps/desktop && npm run tauri dev"
say ""
say "  # 运行一致性/接口测试"
say "  ./scripts/check.sh"
say ""
say "  # 可选组件（浏览器执行器 / 本地语音）"
say "  ./scripts/setup.sh --with-browser --with-voice"

if [ "$OPTIONAL_FAILED" -eq 1 ]; then
  exit 1
fi
