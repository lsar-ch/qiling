# P0-3 macOS 人工安装与界面目检清单

- **候选包**：`apps/desktop/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/Qiling_0.2.0_x64.dmg`（170 MB，2026-11-13 22:30 构建，x86_64 原生，本机 Intel 无需 Rosetta）
- **已核验**：包内 6 只角色资产齐全（cat_vrm / meshy_female 的 model.vrm、pet_cat_walk_test 的 model.glb、qiling 的 model.vrm 均在；default / persona_2 为 2D 程序化角色无模型文件）。
- **目标**：非开发目录安装/打开，人工确认主界面、挂件、6 张角色卡；**不覆盖** `/Applications/Qiling.app`。

---

## 0. 安装前（安全，不破坏现有安装）

1. 双击 DMG 挂载（卷名 `Qiling`）。
2. **不要**直接拖到 `/Applications`（会覆盖现网 `app.qiling.desktop`）。改为把 `Qiling.app` 拖到 `~/Desktop`，重命名为 `Qiling-v0.2-candidate.app`。
3. 在启动正式 App 前，先**退出** `/Applications/Qiling.app`（两者 bundle id 同为 `app.qiling.desktop`，会共享 `~/Library/Application Support/app.qiling.desktop`，同时运行会争用状态/端口）。
4. 首次打开可能被 Gatekeeper 拦截（ad-hoc 签名、未公证）。处理：右键 `Qiling-v0.2-candidate.app` → 打开；或终端 `xattr -cr ~/Desktop/Qiling-v0.2-candidate.app`。

> 说明：本 DMG 为 ad-hoc 签名、未公证（P0-5 待决策）。仅本机候选目检可接受；公开分发前的公证策略见 P0-5。

---

## 1. 主界面 & 挂件

- [x] App 正常启动，无崩溃 / 无空白窗（§5 隔离首启记录）。
- [x] 主界面渲染正常（无控制台报错导致的白屏）（§5 `main-ui-native.png` / `main-ui-after-skip.png`）。
- [x] 桌面挂件（Widget）存在且位置正确（§5 逐角色挂件截图）。
- [x] 生产挂件**不出现红虚线/绿/蓝调试边框或彩色多层轮廓**（2026-11-15 复核通过，根因与证据见 §6）。
- [x] 挂件交互（指针热区）正常（**2026-11-15 用户确认已在既有检测过程中覆盖，按用户指示跳过专项复测**）。

---

## 2. 六张角色卡（逐项确认能加载出模型，而非空卡）

| 角色 ID | 类型 | 目检要点 |
|---|---|---|
| `qiling` | VRM 3D | 模型加载、可交互 |
| `pet_cat_walk_test`（蓝猫）| GLB 3D | 模型加载、走动动画正常 |
| `cat_vrm`（加菲）| VRM 3D | **模型加载（非空卡）** — P0-2 重点 |
| `meshy_female`（绯）| VRM 3D | **模型加载（非空卡）** — P0-2 重点 |
| `default` | 2D 程序化 | 程序化头像渲染正常 |
| `persona_2` | 2D 程序化 | 程序化头像渲染正常 |

- [x] 切换 6 张卡均成功加载对应资产，无「空卡 / 无模型」现象（§5 运行时逐项切换 + 2026-11-15 六角色正确合成截图；角色卡页面逐卡手工目检由用户确认已在既有检测中覆盖）。
- [x] 加菲、绯两只 Meshy 猫确认带模型（`/api/personas` 6 张卡、4 个 3D 资源 HTTP 200，§5）。

---

## 3. 稳定性

- [x] 切换角色、关开挂件、退出再启动均稳定（**2026-11-15 用户确认已在既有检测过程中覆盖，按用户指示跳过专项复测**；§5 另有多轮隔离启动/退出记录）。
- [x] 退出候选 App 后，确认未破坏 `/Applications/Qiling.app` 与既有用户数据（§5：`/Applications/Qiling.app` 始终为 `0.1.0`，隔离 HOME 未写入真实 Application Support）。

---

## 4. 目检完成后清理

- [x] 退出候选 App（2026-11-15 由用户自行退出，主进程与 sidecar 均已结束、8736 无监听）。
- [ ] 删除 `~/Desktop/Qiling-v0.2-candidate.app` / 本机候选副本（用户决定保留，暂不清理）；弹出 DMG 卷。

## 5. 2026-11-14 隔离首启与目检进度（已按 2026-11-15 用户确认收口）

- 已验证 DMG 与桌面现存 `~/Desktop/Qiling.app` **逐文件一致**；版本 `0.2.0`，签名校验通过。`/Applications/Qiling.app` 仍为 `0.1.0`，未触碰。
- 通过 `HOME=/tmp/qiling-p0-3.4phtB0` 隔离数据目录启动候选包；首启模板落入隔离目录，未写入真实用户 Application Support。
- 初次隔离配置将 `setup_completed` 设为 `true` 时未弹原生主界面；将隔离配置临时恢复为 `false` 后，候选 App 自动显示原生「栖灵主界面」，主页正常渲染，首启向导覆盖在前景。截图：`main-ui-native.png`。Safari 截图 `main-ui-safari.png` 仅作补充，不作为原生窗口证据。
- 用户手动跳过首启向导后，原生主界面完整显示；`/api/setup/status` 为 completed，LLM 未配置，`api_key_configured=false`，符合跳过流程预期。截图：`main-ui-after-skip.png`、`widget-after-skip.png`。
- 用户打开「角色卡」页后，原生页面渲染正常，卡片列表对应 6 个 API 角色（另有“新建角色卡”操作）；右侧详情显示当前启用的栖灵。截图：`persona-page-before-switch.png`、`widget-before-manual-switch.png`。手工启用/切换尚待验证。
- 用户在原生「角色卡」页手动启用加菲后，隔离设置 `active_persona_id=cat_vrm`，挂件同步显示加菲模型。截图：`persona-page-after-cat_vrm.png`、`widget-after-cat_vrm.png`。手工切换链路通过（本轮仅人工验证此角色）。
- 用户提供的旧候选右键菜单截图确认仍显示「动作检阅」；截图归档为 `widget-context-menu-old-candidate.png`。检查发现当前源码已用 `import.meta.env.DEV` 同时门控菜单按钮、检阅标记和 AnimalStage 检阅参数，独立代码复查未发现问题。
- 已重新构建桌面生产前端（`npm run build` 通过，dist 中无「动作检阅」文本），并用 Tauri 生成本地 x86_64 `Qiling.app` 候选：`apps/desktop/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/Qiling.app`；版本 0.2.0，`codesign --verify --deep --strict` 通过。不是 DMG 或发布包，未覆盖桌面旧副本或 `/Applications`。
- 用户在新构建挂件上手动打开右键菜单并确认「动作检阅」已消失；截图中剩余项为打开主界面、靠近边缘自动隐藏、角色大小、退出栖灵。菜单项复核通过，截图：`widget-context-menu-new-build.png`。
- 新构建在隔离 HOME 下运行；此验证只确认本地 x86_64 App，不代表旧 DMG 或 Release 已更新。正式发布前仍须从最终候选范围重新完整打包。
- `/api/personas` 返回 6 张角色卡；`cat_vrm/model.vrm`、`meshy_female/model.vrm`、`pet_cat_walk_test/model.glb`、`qiling/model.vrm` 资源请求均为 HTTP 200。`default` 与 `persona_2` 为程序化 2D 角色。
- 通过隔离环境 `PUT /api/settings` 逐项切换 6 个 `active_persona_id`，挂件依次显示对应形象；截图 `widget-{cat_vrm,default,meshy_female,persona_2,pet_cat_walk_test,qiling}.png`。这验证运行时挂件形象加载，不等同于角色卡页面的手工选择验收。
- 隔离环境没有配置 LLM key，`/api/health` 为 HTTP 200 但总体状态 `error`（LLM 未配置）；语音为可选降级项。这不代表安装损坏，但无法验证对话能力。
- **已通过（2026-11-15 复核关闭）**：六个挂件截图中的红、绿、蓝及深色多层轮廓，确认为 macOS 对透明窗口截图时在 `alpha=0` 像素中保留的隐藏 RGB 数据被忽略 alpha 的查看器渲染所致，不是挂件渲染缺陷；真实窗口可见画面干净。根因、复现与证据见 §6。本轮未改渲染代码。
- **2026-11-15 用户收口**：用户确认「指针热区、关开挂件、退出重启、除加菲外角色卡逐卡目检」在之前的检测过程中已顺便测试过，指示**跳过**专项复测。清单 §1–§3 据此回填勾选。此前 macOS 拒绝 `osascript` 辅助功能控制（终端未获 Accessibility 权限）不再构成阻塞；未因此修改 `/Applications/Qiling.app`。
- 前一轮两个孤儿 sidecar（PID 23444、23784）及本轮 sidecar（PID 28863）均确认来自桌面候选包且不监听 8736；`TERM` 无效后已定向强制结束。本轮候选主进程也已退出，端口无监听；桌面候选副本保留，`/Applications/Qiling.app` 仍为 0.1.0。

---

## 6. 2026-11-15 彩色多层轮廓根因复核（挂件外观项通过）

**结论**：此前记录的「红、绿、蓝及深色多层轮廓」不是挂件渲染缺陷，而是 macOS `screencapture -l` 截取透明窗口时，在 `alpha=0` 像素中保留的隐藏 RGB 数据；忽略 alpha 的查看器会把它渲染成围绕角色的多层彩色轮廓，遵守 alpha 的真实窗口画面干净。无需修改渲染代码，本轮零代码改动。

**证据链**

| # | 检查 | 结果 |
| --- | --- | --- |
| 1 | 归档 6 张 `widget-*.png` 遵守 alpha 显示 | 红/绿/蓝调试框色像素均为 0，目视无彩框 |
| 2 | 强制 `alpha=255` 导出 | 出现围绕角色的红/黄绿/深色多层胶囊轮廓，与交接文档描述吻合 |
| 3 | 窗口溯源 | 挂件窗口 ID `286`，逻辑 `430×480`，Retina 2x = `860×960`，与归档截图尺寸一致 |
| 4 | 用运行中的候选重新 `screencapture -x -o -l 286` | 新图彩色残留像素 `3353`，归档 `widget-qiling.png` 为 `3351`；强制 alpha 后轮廓形状一致 → 伪影可稳定复现 |
| 5 | 生产 `dist` 扫描 | JS 中无 `pointer-debug-layer` 等调试 JSX（`import.meta.env.DEV` 门控生效）；CSS 类名残留但无对应 DOM |
| 6 | 不透明全屏截图 | 屏幕右侧挂件角色干净，无彩色轮廓 |

**真实运行验证**

- 隔离 HOME `/tmp/qiling-p0-3-uaStyQ` 启动 `apps/desktop/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/Qiling.app`（0.2.0）；sidecar 监听 `8736`，`/api/health` 返回 `version 0.2.0`（`status=error` 仅因未配 LLM key），`/api/personas` 返回 6 张卡。
- 逐项 `PUT /api/settings` 切换 6 个 `active_persona_id`，各截窗口图并正确合成到不透明浅灰底：6 个角色全部正常加载，无空卡、无彩框。合成图调试色像素除 `meshy_female` 外均为 0；其 2,119 个像素位于角色身体区 `(352,417)–(590,776)`，颜色为 `(236,94,93)` 等红色围巾色，属阈值误判。
- 未运行 `./scripts/check.sh`：零代码改动，遵循「不重跑已通过的可写测试」口径。
- 用户于 2026-11-15 确认挂件外观项修订为通过；候选 App 由用户自行退出，本轮未覆盖 `/Applications/Qiling.app`（仍 0.1.0）。

**证据归档**：`docs/evidence/macos-v0.2-P0-3-alpha-2026-11-15/`

- `comparison-hidden-rgb-vs-composited.png`：左为忽略 alpha 的伪影，右为正确合成的真实窗口。
- `widget-6-personas-clean.png`：6 角色拼图；`widget-<id>-clean.png`：逐角色正确合成单图。
- `widget-qiling-raw-rgba-window-capture.png`：原始 RGBA 窗口截图，保留透明像素隐藏 RGB 数据，供复现。
- 含桌面内容的不透明全屏截图按隐私口径未入库。

**2026-11-15 收口**：挂件指针热区、关开挂件、退出重启稳定性与除加菲外角色卡逐卡目检，均由用户确认已在既有检测中覆盖并指示跳过专项复测，P0-3 人工目检项判定为**通过**。唯一遗留动作是**从最终候选范围重新执行完整 `tauri build` 并重建 DMG**（旧 DMG 早于 11-14 源码改动，不能视为发布包）。

---

## 备注

- 本 DMG 构建于 2026-11-13 22:30，早于 11-14 的 gitignore/授权改动；改动不影响打包内容（模型文件本就在磁盘）。
- **公开 Release（P0-7）前须从最终提交重新 `tauri build` 一次**，确保 web/dist 为最新，再走 P0-4（Windows NSIS）/ P0-5（签名公证）/ P0-6（文案核验）。
