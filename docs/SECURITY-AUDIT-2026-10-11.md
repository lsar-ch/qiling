# M3 安全审计报告（2026-10-11）

> 对应 `docs/RELEASE-PLAN-2026-10-10.md` M3 全库审计。审计时工作区已提交至 `1ae0069`。
> 结论：**无高危项阻塞 v0.1 发布**；cryptography 经复核为 Intel macOS 平台限制 + 零暴露面，保持 48.0.1（见 P1）；前端构建链告警仅影响开发环境。

## 一、总览

| 工具 | 范围 | 结果 |
| --- | --- | --- |
| gitleaks 8.30.1 | 全 git 历史 95 commits（~3.2MB） | **0 leaks** |
| bandit 1.9.4 | `services/ai-service/app`（13,487 行） | 0 High / 0 Medium / 35 Low |
| pip-audit | `services/ai-service/requirements.txt` | 1 包 6 条公告（cryptography 48.0.1） |
| npm audit | `apps/web` 生产依赖 | **0 vulnerabilities** |
| npm audit | `apps/web` devDependencies | 6 High + 2 Moderate（构建链，见下） |
| npm audit | `apps/desktop` | 1 High（source-map-js，间接依赖） |
| cargo audit | `apps/desktop/src-tauri`（397 crate） | 0 漏洞；7 warnings（6 unmaintained + 1 unsound） |
| license 核对 | npm / Python / Rust 全依赖 | 无 GPL/AGPL/LGPL 混入 |

## 二、分级问题清单

### P1 — cryptography（已评估：本机不升级，记录接受）

1. **Python `cryptography` 48.0.1：6 条已知公告（PYSEC-2026-3552/3553/3554），修复版本 49.0.0/50.0.0**
   - pip-audit 报告（3552 与 3553/3554 部分重复计数，实际 3 个独立 CVE）。
   - 处置：升级到约束允许的 49.x 后复跑 `./scripts/check.sh`；若 50.x 需要新 OpenAPI 再评估。升级属依赖变更，按项目规则单独授权。
   - **2026-10-11 复核结论：本机保持 48.0.1，不升级（已授权评估）**。
     - 平台限制：49.0.0/50.0.0 的 macOS wheel **仅 arm64**（PyPI 文件列表核实），本机为 x86_64 Intel，强升会退回源码编译并因缺 OpenSSL 失败；`requirements.txt:13` 已有 `cryptography<49; sys_platform == "darwin" and platform_machine == "x86_64"` 环境标记。
     - 暴露面：应用代码 0 处直接 import cryptography；仅 dashscope 间接依赖，且只用对称加密/序列化（`ciphers/serialization/asymmetric padding`），不碰 3 个 CVE 的 X.509 证书链验证 / PKCS7 EnvelopedData 路径。
     - CVE 性质：3552 为 PKCS7 EnvelopedData Bleichenbacher oracle（需应用解密攻击者数据并回显结果）；3553 为重复自签证书链指数级 DoS；3554 为 name constraints 通配 SAN 逃逸。三者都要求应用主动做证书/PKCS7 校验，栖灵不触达。
     - 后续：Windows（x64）/ macOS arm64 构建环境装到 49.x 即自动满足（环境标记只锁 Intel macOS）；若 Intel 支持周期内要修，路径是本地 OpenSSL 源码编译，收益不值得。

### P2 — 不阻塞，记录跟进

2. **web devDependencies：braces/chokidar/micromatch/fast-glob（DoS 类 High）+ postcss-selector-parser/postcss-nested（Moderate）**
   - 全部经 `tailwindcss@3 → chokidar/fast-glob` 间接引入，仅**本地构建/HMR** 处理可信源码，不进入运行时产物。
   - 唯一修复路径是 `tailwindcss@4`（breaking，配置体系重写）。发布后随 tailwind v4 迁移统一处理，不为发布阻塞。
3. **desktop `source-map-js` 1 High（GHSA-68fv-2mgg-jv7q，DoS）**
   - 间接依赖，只在 devtools/source-map 解析链；非 Tauri 运行时面。`npm audit fix` 为非 breaking 升级，可在下次 desktop 依赖整理时带上。
4. **Rust：7 条 RUSTSEC warning（非漏洞）**
   - 6 个 `unic-*` crate 标记 unmaintained（RUSTSEC-2025-0075/0080/0100/0098 等，经间接依赖引入）；`glib` 1 条 unsound（RUSTSEC-2024-0429，Linux 桌面相关，macOS/Windows 构建不走该路径）。
   - cargo audit 退出码 0；等上游 Tauri/tao 升级传递依赖，不单独 pin。

### P3 — 可接受（bandit Low，35 条）

- `B110 try_except_pass` ×9、`B112 try_except_continue` ×8：集中在后台任务/日志/资源清理（如 `runtime.py` 事件推送、`dashscope.py` 关闭 synthesizer），吞异常是有意降级，不影响输入处理。
- `B101 assert_used` ×9：均在内部不变量检查（ACP stdin/stdout 非空、skills registry 更新结果），非安全边界。
- `B603 subprocess_without_shell_equals_true` ×5、`B404 import subprocess` ×4：全部位于设计内需要起子进程的模块——`agents/acp.py`、`agents/codex.py`、`agents/runtime.py`、`agents/local_office.py`、`agents/office_tools.py`、`mcp/stdio_client.py`。抽查确认均为**参数数组调用、`shell=False`**；办公引擎安装的包名来自内置清单文件而非用户输入（`office_tools.py:117` 注释已说明）。无命令注入面。

## 三、License 白名单核对

- **npm（web/desktop 全量传递依赖）**：MIT、Apache-2.0、ISC、BSD-3-Clause、Apache-2.0 OR MIT。
  - 唯一非软件许可：`caniuse-lite` = **CC-BY-4.0**（浏览器兼容性数据集，构建期使用，注明出处即可，无 copyleft）。
  - 新增 3 个依赖：`i18next`、`react-i18next`、`i18next-browser-languagedetector` 均为 **MIT**，与 PolyForm Noncommercial 无冲突。
- **Python（.venv 约 90 包）**：MIT / BSD 系 / Apache-2.0 / PSF / MPL-2.0 / ISC / Zlib / CC0，无 GPL/AGPL/LGPL；6 条空 license 字段为老旧包元数据缺失，包本身为 MIT/BSD 系（逐包见 pip 元数据）。
- **Rust（397 个第三方 crate，逐一查 crates.io）**：无 GPL/AGPL（唯一 404 是本项目自身 `qiling-desktop`）。
- 结论：依赖许可与 PolyForm Noncommercial 1.0.0 + 作者保留商业授权的协议**兼容**。

## 四、复跑命令

```bash
# 密钥
/tmp/gitleaks git .                       # 0 leaks
# Python
uvx bandit -r services/ai-service/app
uvx --from pip-audit pip-audit -r services/ai-service/requirements.txt
# 前端
(cd apps/web && npm audit)                # 生产 0；devDeps 见 P2
(cd apps/desktop && npm audit)            # 1 High 见 P2
# Rust
(cd apps/desktop/src-tauri && cargo audit)
```

## 五、发布门槛判定

- 硬门槛（密钥泄露 / 高危可利用漏洞 / copyleft 混入）：**全部通过**。
- 待决策：P1 cryptography 升级是否在 v0.1 前做（建议做，预计低风险）。
- 不随本次处理：P2 构建链告警（tailwind v4 迁移另开任务）。
