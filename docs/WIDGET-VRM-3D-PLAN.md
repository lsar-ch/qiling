# 栖灵 挂件 3D 形象（three-vrm）实施方案

> **2026-10-12 状态更新：形象资产自研路线已重新裁定，以
> [`docs/CHARACTER-ASSET-FINAL-PLAN-2026-10-12.md`](CHARACTER-ASSET-FINAL-PLAN-2026-10-12.md) 为最终方案。
> 本文以下内容仅作历史与实现细节参考；涉及"形象从哪来"的结论以最终方案为准。**

日期：2026-09-20　状态：步骤 0-5 已实施（2026-09-20），剩步骤 6 人工验收与 Windows 真机

## 1. 结论

挂件动态走 **three-vrm（VRM 3D 模型 + VRMA 动画）** 路线。可行性已在真实环境验证通过
（Tauri 2.11.5 release 构建 + 与挂件窗口逐字相同的配置，spike 代码在 `/tmp/vrm-tauri-spike/`）：

- 透明合成：不配 `backgroundColor` 也通过，四角像素 `[0,0,0,0]`，84.6% 画布全透明
- 性能：生产渲染配置下 58fps 稳定（p50 17ms / p95 29ms），核显跑 1.9 万面模型无压力
- VRMA 重定向：`createVRMAnimationClip(vrma, vrm)` 内置解决，骨骼确认被驱动
- 口型 tier-1：AnalyserNode RMS → `aa` blendshape，真实 TTS 音频 400 帧中 314 帧张嘴；**必须加 autogain**（否则峰值仅 0.35）

现有 2D 分层路线保留为并行回退（按 persona 的 `avatar_driver` 分流）；非人形角色继续走 2D。

## 2. 生产渲染配置（验证得出，不得随意改）

```ts
new THREE.WebGLRenderer({
  alpha: true,
  premultipliedAlpha: false, // Windows DComp 黑底已知修法
  antialias: false,          // 开 MSAA 掉到 47fps、p95 56ms
  preserveDrawingBuffer: false,
  powerPreference: "low-power",
});
renderer.setPixelRatio(1);   // dpr2 同样触发上述性能劣化
renderer.setClearColor(0x000000, 0);
```

html/body/canvas 背景全透明。首帧 shader 编译卡 0.5-1.9s → 必须异步加载 + 占位图，加载完成后再显示 canvas。

## 3. 资产规格（每个 3D persona 一套）

- VRM 1.0 模型：≤4 万三角面、≤16 材质、≤30 spring bone 关节（超出未验证，视为规格上限）
- 必备表情 15 项：`aa ih ou ee oh`、`blink`、`happy angry sad relaxed neutral`、`lookUp lookDown lookLeft lookRight`
- VRMA 动作片段：11 个 `ActionTrigger` 基名（`idle/listening/thinking/speaking/executing/awaiting_approval/success/error/click/project/hover`）。实操已改为**男/女各一套共享库 + 角色卡多候选**（见第 7 节），不再要求每个 persona 自带一份
- 授权四项边界逐模型确认：允许下载 / 允许改模 / 允许录屏 / 允许商用
- 3D 片段走 `GET /api/motion-library/{variant}/{file}`（共享库）或 `GET /api/personas/{id}/asset/{path}`（角色覆盖）下发

## 4. 实施步骤（纵向切片，每片可构建可验证）

### 步骤 0：依赖安装（需用户批准）

`apps/desktop` 安装 `three`、`@pixiv/three-vrm`、`@pixiv/three-vrm-animation`。
验证：`npm run build` 通过。

### 步骤 1：契约扩展

- `packages/contracts/py/qiling_contracts/character.py:11`：`AvatarDriver` 增加 `"vrm_3d"`
- `packages/contracts/ts/src/character.ts:4`：同步镜像（`test_contracts_sync.py` 强制一致）
- 默认值保持 `procedural_2d`，存量 persona 行为不变

验证：contracts 测试通过。

### 步骤 2：VrmStage 渲染组件

新建 `apps/desktop/src/widget/VrmStage.tsx`：

- 第 2 节渲染配置；异步加载 VRM；加载完成前不显示占位立绘（2026-09-29 起：VRM 角色的 `avatar.png` 是 T-pose 渲染图，始终 `data-hidden=1` 只留给命中区测量，挂件在加载完成前保持透明）
- 显示前执行 `vrm.update(0)` + `mixer.update(0)` 再 `scene.visible = true`（避免闪 bind pose）
- 相机取景用 humanoid 的 head / leftFoot 骨骼计算包围盒
- `Widget.tsx` 分流：persona presentation 的 `avatar_driver === "vrm_3d"` 时渲染 VrmStage，否则走现有 `mascot-layers` 分支（约 1492 行）

验证：dev 模式手动配一个 klee.vrm persona，肉眼确认透明窗口 + 模型显示 + 无首帧闪烁。

### 步骤 3：VRMA 动作映射

- 复用 `apps/desktop/src/widget/actions.ts` 的 trigger 体系，不新造调度
- 按 trigger 名加载对应 `.vrma`；循环类（idle/listening/thinking/speaking/executing/awaiting_approval）用 `LoopPingPong`，一次性动作（success/error/click 等）用 `LoopOnce` 播完回 idle
- 切换一律 `crossFadeTo(0.2s)`（硬切会闪 bind pose）
- 缺片段时静默回退 idle

验证：切 widget 状态 / 点击角色，模型播放对应动作。

### 步骤 4：口型同步 tier-1

- 接入点：`Widget.tsx` `_playAudioBlob`（约 435 行），`source.connect(ctx.destination)` 之间插 AnalyserNode
- RMS → autogain → `aa` 表情权重；仅 `vrm_3d` persona 启用，2D 路径不接
- 眨眼：随机间隔定时器驱动 `blink`，不依赖音频
- tier-2（元音识别口型）已验证 FFT 方案不可行（基频谐波锁死 F1），**明确不做**，除非未来上 LPC/MFCC

验证：真实 TTS 播放时嘴部开合明显；静音时闭合。

### 步骤 5：persona 配置下发

- `services/ai-service/app/core/presentation_bridge.py:86`：`asset` dict 增加 `vrm_url` / VRMA 目录信息（persona 配置声明 `style: "3d"` 时）
- 资产文件放 persona 目录即可被现有 asset 接口服务，无需新路由
- 导入入口（2026-09-20 追加）：角色卡页「形象」区「导入 3D 资产包（.zip）」→ `POST /api/personas/{id}/import3d`；zip 内 model.vrm 必需、vrma/<trigger>.vrma 与 avatar 图可选，整体替换落盘 + 写 yaml + 广播，挂件即时切换

验证：`/api/personas/{id}` presentation 事件带出 vrm 字段；挂件端拿到后自动走 3D。

### 步骤 6：回归收口

- 验收演示 persona：`config/personas/vrm_demo.yaml` + `data/persona-assets/vrm_demo/`（klee.vrm + idle/thinking/success 三个 VRMA），设置里切到它即可看 3D；不切则一切照旧
- `./scripts/check.sh` 全绿 + `apps/desktop` `npm run build`（已完成：244 passed + 构建通过）
- 浏览器冒烟已通过：`?qiling=widget` 下 canvas 渲染 Klee、idle VRMA 循环播放、占位图按预期撤下
- 2D persona 回归：现有角色表现与之前完全一致
- macOS 人工验收：透明、拖动、置顶、双击、动作、口型 —— **2026-09-29 实机 6/6 通过**

## 5. 风险与未验证项

| 风险 | 状态 | 对策 |
| --- | --- | --- |
| Windows WebView2 透明+WebGL | 未验证（Tauri #8020/#4891 有已知问题） | `premultipliedAlpha:false` 为已知修法；落地后需 Windows 真机测 |
| 高面数模型性能 | 仅测过 1.9 万面 | 资产规格硬上限 4 万面；超限模型不上 |
| 首帧 shader 编译卡顿 0.5-1.9s | 已复现 | 异步加载；加载完成前保持透明（不再显示 avatar/T-pose 占位图） |
| WKWebView 不暴露 GPU 信息 | 已确认 | 不检测 GPU，靠第 2 节保守渲染配置兜底 |
| 打包 `.app` 后表现 | 未验证 | 当前 `bundle.active:false` 不受影响；启用打包时补测 |
| VRM/VRMA 授权 | 逐模型 | 资产规格第 4 条边界检查 |

## 6. 明确不做

- tier-2 口型（元音级）：FFT 方案已验证失败，YAGNI
- 非人形角色 3D 化：人形骨骼是 VRM 硬前提，动物/异形留在 2D
- 主界面（apps/web）3D 化：角色只活在挂件窗口

## 7. 动作库与多候选（2026-09-29 定稿）

状态不再固定绑一条动作，改成「状态 → 动作组 → 组内加权随机」，与 2D 动作表同一套思路。

### 分层

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 共享主题库 | `data/motion-library/{male,female}/` | 同性别所有 3D 角色共用一套，不按角色复制；`GET/HEAD /api/motion-library/{variant}/{file}` 下发，白名单只放行 male/female |
| 角色覆盖 | `persona-assets/<id>/vrma/` | 库里没有该片段才回退到这里 |
| 动物线 | `motion_family: animal` 的 2D 动作表 | 猫狗通用一套，不进 VRM 共享库 |

角色卡声明用哪套库 + 多候选：

```yaml
presentation:
  vrm:
    library: female
    actions:
      idle:
      - clip: idle
        weight: 4
      - clip: idle_yawn
        weight: 0.5
        cooldownMs: 45000
```

### 挑片规则

- 一个 trigger 可列多条候选，`weight` 加权随机（缺省 1，0 视为弃用）
- `cooldownMs` 内不再挑同一条；候选全在冷却就保持当前动作，不硬切（与 2D `pickAction` 行为一致）
- 一次性 click/hover 反馈同样走随机；抽回正在播的同一条时直接放行，避免循环动作重播跳帧
- 常驻状态重挑：循环类 trigger（listening / idle / …）按 `idle_action_interval_ms`（带 ±20% 抖动）到点重抽候选。否则一条片段从头循环到尾，多候选永远轮不到。挂件日常多在 listening，靠这条才有变化

### 实现位置

- 纯逻辑挑选：`apps/desktop/src/widget/vrmClips.ts`（自检 `npx tsx apps/desktop/src/widget/vrmClips.ts`）
- 挂件渲染：`apps/desktop/src/widget/VrmStage.tsx`（库优先取片、`play` / `playOneShot` / 空闲重挑）
- 下发：`services/ai-service/app/api/settings.py`（`get_motion_library_file`，复用 `_resolve_persona_asset` 防穿越）
- 动作实验室：`apps/web/src/MotionLabPage.tsx`（总览列出全部候选与权重；改素材只换候选表第一条，不清空其余候选）

### 素材现状

20 个片段里目前只有 `project_alt` 真不同（male = Bboy Hip Hop Move，female = Arms Hip Dance），其余 19 个两个库完全一致。差异化方案见 §8。
已配多候选并实测生效的 trigger：`idle`（+`idle_yawn`）、`speaking`（+`speak_alt`）、`success`（+`success_happy`）、`click`（+`error`）。

## 8. 动作素材工具调研（2026-09-29）

目标：让 `male` / `female` 库有可分辨的内容差异。

**本机已具备的条件**

- Blender 4.5.14 LTS + VRM Add-on（扩展装在 `~/Library/Application Support/Blender/4.5/extensions/blender_org/vrm`）
- 无头 VRMA 往返链路已实测可用：`import_scene.vrma` → 改 F-curve → `export_scene.vrma`
  （54 骨 / 207 条曲线 / 帧范围 1-345 往返成功）。注意 `wm.read_factory_settings` 会重置扩展启用状态，
  顺序必须是「先清场、再启用」。
- `~/Downloads/fbx2vrma-converter`（MIT，tk256ailab）与 19 个 Mixamo FBX 源、20 个已转 VRMA

**GitHub 候选（按价值排序）**

| 工具 | ★ | 许可 | 能力 | 本机可行性 |
| --- | --- | --- | --- | --- |
| [Kirakun0328/text-to-vrma](https://github.com/Kirakun0328/text-to-vrma) | 183 | MIT | 文字 → VRMA；LLM 关键帧引擎走 OpenAI/Claude/兼容 API；ARDY 本地引擎是 NVIDIA GPU 方案 | 浏览器版 `npm install && npm run dev`，用 OpenAI 兼容 key 即可，**不需要 GPU**；ARDY 在本机 Intel Mac 不可用（约 20GB + CUDA） |
| [YuBan834/vrma-lab](https://github.com/YuBan834/vrma-lab) | 6 | Apache-2.0 | 浏览器 VRMA 工作台；**Agent 模式**暴露 `window.vrmaLab` 结构化 SDK：`inspect → edit → review → validate → exportVrma`，自带 FBX→VRMA 快速转换 | 纯前端静态站，`npm ci && npm run dev`；用 Playwright 驱动其 SDK |
| [vrm-c/bvh2vrma](https://github.com/vrm-c/bvh2vrma) | 86 | MIT | BVH → VRMA（web） | 可用，但要自备 BVH 源动作；仓库 2024 年后停更 |
| [Meringue-Rouge/VRM-Spacing-Animation-Baking](https://github.com/Meringue-Rouge/VRM-Spacing-Animation-Baking) | 10 | 见仓库 | Blender 插件：Mixamo 风格手臂/腿部间距调整 + spring bone 烘焙与循环 | 与现有 Blender 管线互补，「站姿宽窄」这类性别化微调最省 |

**排除**

- `test157t/VRM-Assets-Pack-For-Silly-Tavern`（89★，112 个现成动作）与 `reminjp/vrm-dance`：
  仓库**无 LICENSE**，不可用。
- `malaybaku/AnimationClipToVrmaSample`、`saori-eth/vrm-mixamo-retargeter`：分别依赖 Unity、
  Three.js 运行时，能力被上面两条覆盖。

**路径判断**

- 要「造新动作」→ `text-to-vrma`（原创内容，同时服务后续自制资产换掉第三方模型）。
- 要「批量改现有动作」→ `vrma-lab` Agent 模式（比自写 Blender 脚本稳，且带四宫格视觉复核）。
- 只差站姿宽窄这类微调 → Blender 间距插件。

安装任一工具前需先取得用户批准（项目规则：新增依赖须先询问）。

## 9. Blender MCP 调研（2026-09-29）

需求：让 Codex 直接开 Blender 改模型格式、改模型、改动作。

### 首选：[ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender)（29.6k★，MIT，2026-09-27 仍在更新）

- 组成：Blender 内插件（在 Blender 里起 socket server）+ 一个 MCP server（`uvx mcp-for-blender`）。
- 官方文档直接给了 Codex 的接法：`codex mcp add blender -- uvx mcp-for-blender`；Codex 桌面版走
  **Settings → MCP servers → Add server**（STDIO，命令 `uvx mcp-for-blender`）。
- 关键能力：`execute_blender_code`（在 Blender 里跑任意 Python）、场景/对象查询、材质、
  `export_scene`（导出 GLB/FBX）、Poly Haven CC0 资产、Hyper3D / Hunyuan3D 生成模型、视口截图。
- 对本项目的意义：本机已装 VRM Add-on for Blender，所以「导入 VRM / VRMA → 改骨骼与关键帧 →
  导出 VRM / VRMA」可以全部用 Python 驱动；视口截图让改动能肉眼复核，正好补上纯无头脚本
  「改了看不见」的短板。

### 本机安装前置（三项都需要用户批准）

1. `uv` 未安装，且本机没有 brew → 用官方脚本 `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. `uvx mcp-for-blender install-addon`，然后在 Blender 里启用插件并点 **Start MCP Server**
   （Blender GUI 必须开着；它不是无头方案）
3. `codex mcp add blender -- uvx mcp-for-blender` → 会写入 `~/.codex/config.toml`（全局配置）

### 注意

- `execute_blender_code` 是真·任意代码执行；`BLENDER_MCP_SAFE_MODE=1` 可拦文件 / 网络 / 拉起外部进程。
- 遥测默认只上报匿名使用记录（工具名、耗时、版本、系统），提示词、代码、截图、场景数据默认不上报。
- 它让 Blender「可被操作」，但不自己产生动作内容；动作素材仍要靠源素材或 text-to-motion（见 §8）。

### 备选

- [arjun988/blender-skills](https://github.com/arjun988/blender-skills)（245★，MIT）：94 个 Blender 技能包，明确支持 Codex。
- [dcc-mcp/dcc-mcp-blender](https://github.com/dcc-mcp/dcc-mcp-blender)（41★，MIT）：DCC MCP 生态的 Blender 插件。
- [sandraschi/blender-mcp](https://github.com/sandraschi/blender-mcp)（51★，MIT）：无头 Blender + FastMCP，41 个工具。
- [squall01337/mixamo-llm-mocap](https://github.com/squall01337/mixamo-llm-mocap)（323★，许可证 NOASSERTION）：
  视频 → Mixamo 骨架动画。是**动作来源**不是编辑器，依赖 GVHMR 推理（重 GPU），本机跑不动。

### 实际安装状态（2026-09-29）

已装完，`~/.codex/config.toml` 语义比对结果：只新增 `+mcp_servers.blender.command`，
唯一删除是 `node_repl` 的空 `args = []`（等价），其余键值零变化。

1. `uv` 0.12.20 → `~/.local/bin/uv`
2. Blender 插件 → `~/Library/Application Support/Blender/4.5/scripts/addons/blender_mcp.py`（protocol 11）
3. MCP server 注册：`codex mcp add blender -- /Users/lxb/.local/bin/mcp-for-blender`
   （用**全路径**：GUI 启动的 Codex 不继承 shell PATH）

**Intel Mac 必踩的坑**：`mcp-for-blender` → `mcp` → `pyjwt[crypto]` → `cryptography`，会解析到
50.0.1；该版本起不再发 x86_64 macOS wheel，退化成源码编译再因缺 OpenSSL 失败（与 `dashscope`
那次同一根因）。解法是先写约束再装：

```bash
printf 'cryptography<49\n' > /tmp/uv-constraints.txt
uv tool install --constraints /tmp/uv-constraints.txt mcp-for-blender
```

用 `uv tool install` 而非 `uvx`，是为了把工具落成独立 venv，运行时不再解析依赖；
`uv tool upgrade` 时要重新带上同一约束。

**尚未做的两步（需人工）**

1. Blender → Edit → Preferences → Add-ons → 启用「Interface: MCP for Blender」，在 3D 视图侧栏
   按 N 打开 **MCP for Blender** 面板，点 **Start MCP Server**
2. 重启 Codex，新的 MCP 工具才会加载

**安全**：`execute_blender_code` 是任意 Python 执行；需要收紧时给 server 加
`BLENDER_MCP_SAFE_MODE=1` 环境变量。

