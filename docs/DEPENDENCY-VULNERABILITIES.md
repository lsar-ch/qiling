# 依赖漏洞待办记录

> 记录时间：2026-09-13
> 环境：Windows 10.0.19045，Node v24.21.0，npm 11.19.0
> 触发场景：Windows 迁移后执行 `npm install` 时 npm audit 报告
> 当前处置：**暂不修复，记入待办，等整轮迁移验收通过后单独评估**

## 1. 结论速览

`apps/web` 和 `apps/desktop` 两个前端包在安装后均报告 **2 个漏洞**（1 moderate + 1 high），
根因是**同一个**：`vite` 及其间接依赖 `esbuild` 版本偏低。

| 包 | 严重级别 | 是否直接依赖 | 当前版本 | 修复目标版本 | 修复性质 |
|---|---|---|---|---|---|
| vite | **high** | 是 | 5.4.21 | 8.3.0 | 跨 3 个大版本（major） |
| esbuild | moderate | 否（被 vite 牵连） | 0.21.5 | 随 vite 升级 | 间接 |

两个包（web / desktop）的 devDependencies 中 `vite` 版本一致，所以报告内容完全相同。

## 2. 漏洞明细

### 2.1 vite — high（CVSS 7.5）

直接依赖。实际是 3 条 advisory 合并计为一个 high：

| advisory | 标题 | 级别 | 影响版本 |
|---|---|---|---|
| GHSA-fx2h-pf6j-xcff | `server.fs.deny` bypass on Windows alternate paths | **high** | <= 6.4.2 |
| GHSA-4w7w-66w2-5vf9 | Path Traversal in Optimized Deps `.map` Handling | moderate | <= 6.4.1 |
| GHSA-v6wh-96g9-6wx3 | launch-editor: NTLMv2 hash disclosure via UNC path handling on Windows | moderate | <= 6.4.2 |

### 2.2 esbuild — moderate（CVSS 5.3）

间接依赖，由 vite 引入。

| advisory | 标题 | 级别 | 影响版本 |
|---|---|---|---|
| GHSA-67mh-4wv8-2f99 | esbuild enables any website to send any requests to the development server and read the response | moderate | <= 0.24.2 |

## 3. 为什么不立即修复

1. **影响面限于开发服务器。** 三条 advisory 全部作用于 `vite dev` / 开发服务器场景
   （`server.fs.deny`、optimized deps、launch-editor）。**不影响 `npm run build` 产物，也不影响生产运行**。
   本项目是本地单机应用，开发服务器只监听本机，实际暴露面很低。
2. **`npm audit fix --force` 会强制跨大版本升级。** 修复目标是 `vite@8.3.0`，
   相对当前 `5.4.21` 跨越 6/7/8 三个大版本。vite 大版本间存在破坏性变更，
   很可能直接打挂现有构建与 Tauri 集成，风险远大于漏洞本身。
3. **遵守迁移纪律。** 依据 `WORKBUDDY-WINDOWS-MIGRATION.md` 第 12 节
   「不为了通过测试修改产品逻辑」，依赖大版本升级属于同类性质的改动，
   不应混入本轮 Windows 平台回归。

## 4. 后续处置建议（待整轮验收通过后再做）

> **决策（2026-09-14）：采用方案 B 并挂账。**
> 归口到路线图 **P2 发布加固**下的独立「依赖维护」条目（仓库无 V2/V3 里程碑命名）。
> 提前触发条件：① dev server 需暴露到局域网/公网；② 新依赖的 peer 要求 vite ≥ 6/7；
> ③ 发布门禁要求 `npm audit` 零 high。日常动作：每季度重跑一次 `npm audit`，只记录不修。
> 完整影响面清单见本文第 7 节；结论摘要见 `docs/WINDOWS-MIGRATION-2026-09.md` 第 4 节。

按风险从低到高，任选其一：

- **方案 A（推荐，最小改动）**：先只升到 vite 6.x 最新，验证 web build + desktop typecheck + tauri dev 三处正常，
  再逐个大版本往上走。每一步都跑一遍 `npm run build` 与 `npm run typecheck`。
- **方案 B（观察）**：若项目长期不暴露开发服务器到局域网/公网，可暂缓，
  仅在 `docs/CROSS-PLATFORM-TESTING.md` 中记一笔已知项。
- **方案 C（不推荐）**：`npm audit fix --force` 一步到位。仅在确认有完整回退手段
  （git 干净状态 + 可重建 node_modules）时尝试。

**任一方案执行前请先确认**：
- `git status` 无未提交改动，或有独立分支承载；
- 两个 `package.json` + `package-lock.json` 已提交，便于回退；
- 升级后必须重跑第 8 节三项检查与第 10 节回归清单。

## 5. 复现命令

```powershell
cd D:\Projects\desktop-assistant\apps\web
npm audit

cd D:\Projects\desktop-assistant\apps\desktop
npm audit
```

## 6. 相关环境噪音（非问题，一并记录）

- `npm warn install-scripts esbuild@0.21.5 (postinstall: node install.js) not yet covered by allowScripts`
  —— npm 11 默认拦截安装脚本。**实测不影响 vite build**：
  esbuild 的平台二进制走 `optionalDependencies`，`@esbuild/win32-x64/esbuild.exe` 已正常落地。
  若将来构建真报缺二进制，用 `npm install-scripts approve esbuild` 放行。
- `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated`（pytest 收集阶段）
  —— starlette 内部对 anyio 旧写法的引用，第三方库噪音，与项目代码无关。

---

## 7. vite 升级影响面（2026-09-14 评估）

修复目标 `vite@8.3.0`，相对当前 `5.4.21` 跨 v6 / v7 / v8 三个大版本。逐项对照本项目实际用法：

### 7.1 当前事实

| 项 | 值 |
|---|---|
| `vite` | `^5.4.0`（实装 5.4.21，`apps/web` 与 `apps/desktop` 各一份） |
| `esbuild` | 0.21.5（vite 内部依赖） |
| `@vitejs/plugin-react` | `^4.3.0`（实装 4.7.0，peer: `^4.2 \|\| ^5 \|\| ^6 \|\| ^7`，**已覆盖 vite 7**） |
| Node（macOS 本机） | v22.23.2 / npm 10.9.8 |
| Node（Windows） | v24.21.0 / npm 11.19.0 |
| `apps/web` 附加 | tailwindcss 3.4.19、postcss 8.5.28、autoprefixer 10.5.5 |

### 7.2 本项目实际用到的 vite 功能（影响面边界）

两个 `vite.config.ts` 都极简，合计只用到：

- `plugins: [react()]`
- `server.port` / `server.strictPort`（5173 / 1420）
- `server.proxy["/api"]` → `http://127.0.0.1:8736`，`changeOrigin` + **`ws: true`**
- `server.watch.ignored: ["**/src-tauri/**"]`
- `build.outDir` / `build.emptyOutDir`

**未用到**（因此对应破坏性变更不触及）：`resolve.conditions`、`build.rollupOptions` /
`manualChunks` / `commonjsOptions`、`optimizeDeps.esbuildOptions`、`build.lib`、
Sass、`splitVendorChunkPlugin`、`transformIndexHtml` 的 `enforce`/`transform`、
`fast-glob` 专有 glob 语法、`legacy` 插件。

### 7.3 逐版本变更 × 本项目

| 变更 | 出处 | 对本项目影响 |
|---|---|---|
| Node 要求提升到 20.19+ / 22.12+（不再支持 18） | v7 | 无阻塞：本机 22.23.2 ✅、Windows 24.21.0 ✅ |
| `resolve.conditions` 默认值调整 | v6 | 未自定义，不受影响 |
| `fast-glob` → `tinyglobby`（brace 范围语法不再支持） | v6 | 未在配置里写 glob 模式，不受影响 |
| Sass 默认 modern API / v7 移除 legacy API | v6 / v7 | 项目未用 Sass |
| `build.lib` 产物 CSS 文件名变化 | v6 | 未用 lib 模式 |
| postcss-load-config 升到 v6 | v6 | **需验**：web 有 tailwind + postcss，确认 tailwind 配置仍被加载 |
| 默认 `build.target` → `baseline-widely-available`（v7：Chrome 107/Safari 16；v8 再升 Chrome 111/Safari 16.4） | v7 / v8 | 产物语法目标更保守/更激进均只影响浏览器下限；本项目是 Tauri 内嵌 webview + 本机浏览器，风险低，但**升级后应跑一次真机界面确认无白屏** |
| 移除 `splitVendorChunkPlugin`、`transformIndexHtml` 的 `enforce`/`transform` | v7 | 未使用 |
| 引擎换成 **Rolldown + Oxc**，不再依赖 esbuild / Rollup | v8 | 正效应：**esbuild moderate 漏洞随之消失**；同时需验构建产物行为 |
| `build.rollupOptions` → `build.rolldownOptions`（旧名保留但废弃） | v8 | 未配置 rollupOptions，不受影响 |
| `build.commonjsOptions` 变 no-op；`optimizeDeps.esbuildOptions` 废弃 | v8 | 未使用 |
| `output.manualChunks` 对象形式不再支持 | v8 | 未使用 |
| `build()` 失败时抛 `BundleError` | v8 | 无自定义构建脚本，低风险 |
| 官方过渡包 `rolldown-vite`（Vite 7 + Rolldown） | v7/v8 | 可作中间验证手段，非必须 |

### 7.4 升级后必须实测的四点

1. `apps/web`：`npm run build`（含 `tsc --noEmit`）产物体积与产物可跑；
2. `apps/desktop`：`npm run build` + `npm run typecheck`；
3. **`server.proxy` 的 `ws: true`**：v6 起 WebSocket upgrade 请求会先经过 `bypass` 逻辑，
   本项目未配置 `bypass`，理论风险低，但要确认挂件事件流（WS）与 `/api` 代理仍通；
4. **Tauri dev 集成**：`devUrl` 仍是 `http://localhost:1420`、`beforeDevCommand: npm run dev`
   不变；Tauri CLI 2.11.4 只负责起 `npm run dev`，不直接依赖 vite API，风险低，
   但需真跑一次 `npm run tauri dev`。

### 7.5 依赖连带

- `@vitejs/plugin-react` 4.7.0 的 peer 已含 `^7.0.0` → **升到 vite 7 无需动它**；
- 若要一次升到 **vite 8**，需同步升 `@vitejs/plugin-react` 到支持 v8 的版本
  （以目标版本 `peerDependencies` 为准），并按需对齐 `@types/react` / `react` 小版本；
- `apps/web` 的 tailwind / postcss / autoprefixer 与 vite 大版本无强绑定，但见 7.4-3 的 tailwind 验证。

### 7.6 建议路径

按 `## 4. 后续处置建议` 的**方案 A**：vite 5 → 6.x → 7.x（此处 plugin-react 不用动）
→ 8.x（此处需连带升 plugin-react）。每步跑 7.4 的四项 + `./scripts/check.sh`。

**关于「停在 vite 7」**：本机 `npm audit` 给出的受影响区间是
`vite <= 6.4.2`（high）与 `esbuild <= 0.24.2`（moderate），照此 v7.0.0 起本应脱离两者。
但 `npm audit` 的一键修复只会报 `vite@8.3.0`（它按整棵依赖树算最小修复），
**不能据此认定 v7 一定清零** —— 升级到 v7 后必须重新跑一次 `npm audit` 确认。
若 v7 已清零，则「停 v7」是风险最小的选择（无需换 Rolldown 引擎，无需连升 plugin-react）。
