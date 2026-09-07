// DeskMate TS 类型镜像。
// 规则：单一事实源是 packages/contracts/py（pydantic）。
// 修改任何镜像类型必须同步 py 端，并运行 services/ai-service 的一致性测试
// tests/test_contracts_sync.py。

export type { AgentInfo, AgentIntegrationStatus } from "./agent";
export type { EventEnvelope, EventSource, EventType } from "./events";
export type { WidgetState, WidgetStatusReport } from "./widget";
export type { RiskLevel, Task, TaskCategory, TaskStatus } from "./task";
export type { ApprovalRequest, ApprovalStatus } from "./approval";
export type {
  CompiledMemory,
  DocOverview,
  MemoryBlock,
  MemoryDoc,
  MemoryEntrySummary,
  MemoryLayer,
  MemorySection,
  SearchHit,
} from "./memory";
export type { ConversationMessage, MessageRole } from "./conversation";
export type { VoiceProvider, VoiceParams, VoiceSettings } from "./voice";
