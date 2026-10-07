# packages/contracts

前后端共享数据结构的权威定义，防止消息格式漂移。

## 规则

- **单一事实源**：`py/`（pydantic，包名 `qiling-contracts`），所有跨模块结构先在这里定义。
- **镜像类型**：`ts/` 中的类型必须与 `py/` 保持一致；两者靠约定同步。
- **一致性测试**：`services/ai-service/tests/test_contracts_sync.py` 会逐字段比对镜像接口与 pydantic 模型，改动后必须运行。

## 当前包含

| 结构 | 文件 | 文档依据 |
|---|---|---|
| EventEnvelope / 事件类型 | py: events.py · ts: events.ts | V1-INTERFACES §3 |
| WidgetState / 状态上报 | py: widget.py · ts: widget.ts | V1-INTERFACES §7 |
| Task / 分类 / 风险 / 状态 | py: task.py · ts: task.ts | V1-INTERFACES §6 |
| ApprovalRequest | py: approval.py · ts: approval.ts | V1-INTERFACES §11 |
| Conversation | py: conversation.py · ts: conversation.ts | — |
| Memory DocOverview | py: memory.py · ts: memory.ts | V1-MEMORY |
| VoiceSettings | py: voice.py · ts（暂缺） | VOICE-PIPELINE |

## 变更流程

1. 修改 `py/qiling_contracts/` 中模型。
2. 同步修改 `ts/src/` 对应镜像。
3. 运行 `services/ai-service` 下的 `python -m pytest tests/test_contracts_sync.py -q`。
4. 有结构性变更时更新 `examples/` 样例。
