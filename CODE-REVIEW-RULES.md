# 代码审查与安全规则

## 目标

AI 生成代码进入 栖灵 前，必须同时通过自动化工具和最小人工确认。
所有修复以「不破坏现有功能、不新增依赖」为前提。

## 硬规则（必须遵守）

- `subprocess` 只用参数列表，禁止 `shell=True`。
- 所有上传 / 文件读取必须设置大小上限。
- zip / tar 解压必须防路径穿越，并限制解压后总大小和条目数。
- 文件路径拼接必须 `resolve()` + `relative_to()` 校验。
- 禁止 `eval` / `exec` / `pickle` / `yaml.load`；配置统一用 `yaml.safe_load`。
- 临时文件用 `tempfile.NamedTemporaryFile` 或 `tempfile.mkstemp`，禁止 `tempfile.mktemp`。
- 禁止硬编码密钥；密钥从 `.env` 或系统凭据库读取，且不入库。
- 状态变更接口必须通过认证或 `Origin` / `Host` 校验；本地态至少要绑定 loopback。
- 新增逻辑必须带最小测试。

## 自动门禁

- workflow：`.github/workflows/security-scan.yml`
- 工具：`Semgrep`、`Bandit`、`pip-audit`、`cargo-audit`、`npm audit`、`gitleaks`
- 初版为报告模式，不阻断开发；中危及以上由人工确认修复，确认后再逐步开启阻断。

## 修复优先级

1. 真实可利用问题：认证缺失、命令执行、路径穿越、密钥泄露。
2. 中危写法：不安全的临时文件、硬编码敏感路径、危险反序列化。
3. 低危 / 风格问题：`try/except: pass`、`assert` 等，按需清理。
4. 本地 `http://127.0.0.1` / `ws://` 属于桌面助手预期行为，不强行改 HTTPS；需要时用 `# nosemgrep` 标注并说明原因。

## 禁止事项

- 不重构无关代码，不删除用户或其他工具留下的改动。
- 不通过删除测试、吞异常或增加忽略规则来制造「通过」。
- 不把扫描报告当作最终验收，关键路径必须有人工复核。
