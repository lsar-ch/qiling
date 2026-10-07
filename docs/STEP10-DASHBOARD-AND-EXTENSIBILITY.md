# Step 10: Dashboard 信息可视化 + 扩展性预留

> 状态：已完成 2026-09-09（规划 → 实现 → 复查 → 修复）
> 依据：灵言 LingYan 开源数字人系统调研 + 栖灵 当前架构

## 背景

灵言项目展示了数字人系统的完整链路：LLM → TTS → 口型驱动 → 输出。
栖灵 当前已完成 Step 1~9，主链路功能齐全但信息可视化不足。
本 step 聚焦四个方向：

1. **信息可视化** — Home 页面加入系统仪表盘
2. **接口预留** — RecordingSession 契约 + 后端 stub
3. **降级细化** — CPU/GPU 双模式 + 明确降级路径
4. **形象定制准备** — CharacterConfig 契约 + Settings 占位

## 目录变更总览

```
packages/contracts/py/qiling_contracts/
├── recording.py          ← 新增：RecordingSession 契约
└── character.py          ← 新增：CharacterConfig 契约

packages/contracts/ts/src/
├── recording.ts          ← 新增：对应 TS 类型
└── character.ts          ← 新增：对应 TS 类型

services/ai-service/app/api/
├── recording.py          ← 新增：录制接口 stub（HTTP 200 + TODO）
└── health.py             ← 修改：加入 performance_mode 字段

services/ai-service/app/config.py   ← 修改：加入 PerformanceMode 配置项
services/ai-service/app/api/settings.py  ← 修改：settings schema 加入性能模式

apps/web/src/
├── App.tsx               ← 修改：Home 页加入 Dashboard 卡片
└── api.ts                ← 修改：HealthResponse + AppSettings 类型扩展
```

---

## 模块 1：Home 仪表盘信息可视化

### 目标

在 Home 页面顶部展示系统运行概览，让用户一眼看清：服务健康、语音链路状态、记忆模式、执行器状态、最近活动。

### 1.1 后端变更

**`services/ai-service/app/api/health.py`** — 扩展 HealthResponse：

```python
# 新增字段加入 health() 返回 dict：
"performance_mode": "balanced",  # "balanced" | "quality" | "lite"
"voice_pipeline": {
    "stt_ready": bool,           # STT 供应商是否可用
    "tts_ready": bool,           # TTS 供应商是否可用
    "vad_working": bool,         # VAD 是否在监听
    "degradation_reason": str | None,  # 如 "no_api_key" / "disabled"
},
"recent_activity": [             # 最近 5 条事件摘要
    {"event_type": str, "timestamp": str, "summary": str}
],
"memory_stats": {                # 记忆统计
    "total_entries": int,
    "obsidian_linked": bool,
    "last_compile": str | None,
},
```

**注意**：`voice_pipeline` 和 `memory_stats` 不应暴露任何密钥或文件内容，只暴露布尔开关和计数。

### 1.2 前端变更

**`apps/web/src/api.ts`** — 扩展类型：

```typescript
export interface HealthResponse {
  // ... 现有字段 ...
  performance_mode: "balanced" | "quality" | "lite";
  voice_pipeline: {
    stt_ready: boolean;
    tts_ready: boolean;
    vad_working: boolean;
    degradation_reason: string | null;
  };
  recent_activity: Array<{
    event_type: string;
    timestamp: string;
    summary: string;
  }>;
  memory_stats: {
    total_entries: number;
    obsidian_linked: boolean;
    last_compile: string | null;
  };
}
```

**`apps/web/src/App.tsx`** — Home 页新增 Dashboard 卡片：

```
┌─────────────────────────────────────────────────────────────┐
│  系统状态                                                     │
├──────────────┬──────────────┬──────────────┬───────────────┤
│ 服务         │ 语音链路     │ 记忆          │ 执行器         │
│ ● 运行中     │ ● STT ✅    │ L3 档案      │ Codex ✅      │
│ uptime 12分  │ ○ TTS ⚠️    │ Obsidian 已连 │ Claude 未安装  │
│              │ △ VAD 监听中 │ 条目 347      │               │
│ 性能模式: 均衡│ 降级原因: 未配置Key │ 上次编译: 今天 08:30  │               │
└──────────────┴──────────────┴──────────────┴───────────────┘
最近活动 (近30分钟):
  • 08:34  conversation.completed — "栖灵 项目状态检查"
  • 08:30  task.completed — "MCP 进程清理"
  • 08:26  memory.updated — L2/user_preferences.md
```

### 1.3 验收

- Home 页顶部出现系统状态卡片，无 JS 错误
- 所有服务离线时降级为灰色占位，不崩溃
- WebSocket 断开时刷新按钮可用

---

## 模块 2：RecordingSession 接口预留

### 目标

预留录制会话的数据结构，为将来"把对话/任务过程录制成视频"能力铺路。当前只建契约 + 空 API endpoint。

### 2.1 新增契约

**`packages/contracts/py/qiling_contracts/recording.py`**：

```python
from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field

class RecordingFormat(StrEnum):
    video_webm = "video/webm"
    video_mp4 = "video/mp4"
    audio_wav = "audio/wav"
    audio_mp3 = "audio/mpeg"

class RecordingMode(StrEnum):
    conversation = "conversation"   # 录制对话文本 + 音频
    task_execution = "task_execution"  # 录制任务执行过程 + 屏幕
    digital_human = "digital_human"   # 数字人口型 + 音频 + 画面

class RecordingSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:10]}")
    conversation_id: str | None = None
    task_id: str | None = None
    mode: RecordingMode = RecordingMode.conversation
    format: RecordingFormat = RecordingFormat.video_webm
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: str | None = None
    output_path: str | None = None    # 本地文件路径
    duration_s: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "recording"         # recording | processing | completed | failed

    model_config = {"extra": "forbid"}
```

**`packages/contracts/ts/src/recording.ts`**：镜像上面的类型定义。

### 2.2 新增 API stub

**`services/ai-service/app/api/recording.py`**：

```python
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["recording"])

@router.get("/recording/status")
async def recording_status(request: Request) -> dict:
    """当前是否有活跃录制会话。"""
    # TODO: 接入实际录制管理器
    return {"active_session": None, "message": "录制功能待实现"}

@router.post("/recording/start")
async def recording_start(request: Request, body: dict) -> dict:
    """开始录制。"""
    return {"status": "not_implemented", "message": "录制功能待实现"}

@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    """停止录制并导出。"""
    return {"status": "not_implemented", "message": "录制功能待实现"}
```

在 `services/ai-service/app/api/__init__.py` 注册 router。

### 2.3 验收

- `GET /api/recording/status` 返回 200，不报错
- 契约一致性测试通过（`tests/test_contracts_sync.py`）

---

## 模块 3：降级逻辑细化（CPU/GPU 双模式）

### 目标

明确三种性能模式，每种模式决定哪些能力启用/降级。参考灵言的 GPU 真口型 + CPU 轻量演示双模式。

### 3.1 性能模式定义

| 模式 | 说明 | LLM | STT | TTS | 挂件动画 | 录制 |
|:---|:---|:---|:---|:---|:---|:---|
| `quality` | 全功能 | 默认模型 | 启用 | 启用 | 完整动画 | 支持 |
| `balanced` | 均衡（默认） | 默认模型 | 启用 | 启用 | 简单状态切换 | 不支持 |
| `lite` | 资源节省 | echo/轻量模型 | 禁用 | 禁用 | 静态图片 | 不支持 |

### 3.2 后端变更

**`services/ai-service/app/config.py`** — 新增：

```python
from enum import StrEnum

class PerformanceMode(StrEnum):
    QUALITY = "quality"
    BALANCED = "balanced"
    LITE = "lite"

# 在 AppSettings 或 GlobalSettings 中加入：
performance_mode: PerformanceMode = PerformanceMode.BALANCED
```

**`services/ai-service/app/api/health.py`** — 在 health 响应中加：

```python
"performance_mode": settings.performance_mode,
"voice_pipeline": {
    "stt_ready": speech.stt_enabled,
    "tts_ready": speech.tts_enabled,
    "vad_working": speech.vad_listening,
    "degradation_reason": speech.get_degradation_reason(),
},
```

**`services/ai-service/app/api/settings.py`** — SettingsUpdate 加入：

```python
performance_mode: str | None = None
```

### 3.3 前端变更

**`apps/web/src/api.ts`** — AppSettings 加入：

```typescript
performance_mode: "quality" | "balanced" | "lite";
```

**`apps/web/src/App.tsx`** — Settings 页加入性能模式选择器：

```tsx
<label className="flex flex-col gap-1.5 text-xs text-muted">
  性能模式
  <select ... value={settings.performance_mode}
    onChange={(e) => updateSetting("performance_mode", e.target.value)}>
    <option value="quality">高质量（全功能）</option>
    <option value="balanced">均衡（默认）</option>
    <option value="lite">轻量（仅文字）</option>
  </select>
  <small className="text-[11px] text-muted">
    轻量模式关闭语音和动画，适合低内存环境或无 GPU 设备。
  </small>
</label>
```

### 3.4 降级逻辑

当前已有基础降级（STT/TTS 失败返回 503）。本次细化：

1. `lite` 模式启动时：强制禁用 STT/TTS，挂件只显示静态角色
2. `balanced` 模式：STT/TTS 任一不可用时显示 warning badge
3. `quality` 模式：全功能，但 GPU 不可用时 TTS 降级到 CPU-only 模型

### 3.5 验收

- 切换性能模式后重启服务，`GET /api/health` 返回正确模式
- `lite` 模式下语音按钮置灰且不可点击
- `./scripts/check.sh` 全部通过

---

## 模块 4：形象训练/定制准备

### 目标

建立 CharacterConfig 契约，在 Settings 页预留形象配置区域，为将来形象训练、口型同步、虚拟摄像头预留扩展点。当前不做实际训练能力，只做接口和数据层。

### 4.1 新增契约

**`packages/contracts/py/qiling_contracts/character.py`**：

```python
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

CharacterStyle = Literal["2d_static", "2d_animated", "lip_sync", "live2d", "3d"]

class CharacterConfig(BaseModel):
    """角色卡的基础配置，V1 只支持 2d_static 和 2d_animated。"""
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    style: CharacterStyle = "2d_static"
    avatar_asset: str = ""          # 静态图片路径或占位符
    animation_set: str = ""         # 动画集名称（用于 2d_animated）
    lip_sync_model: str | None = None  # 口型同步模型（未来）
    training_status: str = "none"   # none | pending | training | ready | failed
    training_progress: float = 0.0  # 0.0 ~ 1.0
    reference_images: list[str] = Field(default_factory=list)
    voice_match: str | None = None  # 匹配的音色 ID

    model_config = {"extra": "forbid"}
```

**`packages/contracts/ts/src/character.ts`**：镜像上述类型。

### 4.2 前端预留

**`apps/web/src/App.tsx`** — Settings 页新增「角色形象」分组（当前只展示占位提示）：

```tsx
<div className="rounded-lg border border-line bg-white shadow-sm p-5">
  <h3 className="text-sm font-semibold text-ink mb-3">角色形象</h3>
  <div className="text-xs text-muted py-4 text-center">
    形象训练功能正在开发中。当前使用静态角色图片，后续将支持自定义形象训练和口型同步。
  </div>
  <div className="grid grid-cols-3 gap-3">
    {/* 将来渲染角色缩略图网格 */}
    <div className="aspect-square rounded-lg bg-surface-secondary border border-line flex items-center justify-center">
      <span className="text-xs text-muted">当前形象</span>
    </div>
  </div>
</div>
```

### 4.3 验收

- 契约一致性测试通过
- Settings 页显示形象分组占位区域，无报错
- 不影响现有功能

---

## 执行顺序

| 顺序 | 模块 | 工作量 | 依赖 |
|:---:|:---|:---:|:---|
| 1 | 模块 3：降级逻辑细化 | 小 | 无 |
| 2 | 模块 4：形象训练准备 | 小 | 无 |
| 3 | 模块 2：RecordingSession 预留 | 小 | 无 |
| 4 | 模块 1：Dashboard 信息可视化 | 中 | 模块 3 完成（需要 voice_pipeline 数据） |

每个模块完成后跑 `./scripts/check.sh` 验证。

---

## 与灵言的差距说明

| 能力 | 灵言 | 栖灵 规划 |
|:---|:---|:---|
| 口型同步驱动 | ✅ 实时 | V2 预留接口，V1 不做 |
| WebRTC 实时预览 | ✅ | V1 不需要（桌面应用） |
| 虚拟摄像头输出 | ✅ | V2 候选 |
| 批量视频生成 | ✅ | V2 候选 |
| 形象训练 | ✅ | V2 预留契约 |
| 管理控制台仪表盘 | ✅ | **本 step 实现** |
| CPU/GPU 双模式 | ✅ | **本 step 实现** |
| 录制导出 | ✅ | **本 step 预留接口** |

核心差异：灵言是独立的数字人产品，栖灵 是桌面 AI 助理。数字人能力作为扩展点预留，不抢占 V1 主线。

---

## 实施记录（2026-09-09）

**合入范围**
- 契约：`packages/contracts/py/qiling_contracts/recording.py`（新建）、`character.py`（新建）、TS 镜像 `recording.ts` / `character.ts`（新建），py/ts `__init__`/`index` 导出同步
- 后端：`config.py`（PerformanceMode + 持久化）、`api/settings.py`、`api/health.py`（performance_mode / voice_pipeline / recent_activity / memory_stats）、`api/voice.py`（lite 禁用识别/合成 + status 报告一致）、`api/recording.py`（3 个 stub）、`core/bus.py`（EventHub.recent）、`main.py`（注册 router）
- 前端：`apps/web/src/api.ts`（类型扩展）、`App.tsx`（Home「系统状态」仪表盘 + Settings 性能模式/角色形象占位）
- 测试：`tests/test_contracts_sync.py`（MIRROR_MAP +2）、`tests/test_step10_backend.py`（新建 4 组用例）

**复查修复（code review 有条件放行后）**
- P1：`/api/voice/status` 在 lite 模式下此前仍报 `enabled: true`，与 health 自相矛盾 → 现报告 disabled 且 activation 关闭
- P1：`RecordingFormat` 枚举值改为 MIME（`video/webm` 等），py/TS 同步
- P2：health `memory_stats` 对只读目录容错；recent_activity 摘要截断至 120 字符

**验证**
- `./scripts/check.sh`：77 passed + Web/Desktop typecheck 通过
