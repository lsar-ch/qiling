// DeskMate TS 类型镜像。
// 规则：单一事实源是 packages/contracts/py（pydantic）。
// 修改任何镜像类型必须同步 py 端，并运行 services/ai-service 的一致性测试
// tests/test_contracts_sync.py。

export type { AgentInfo, AgentIntegrationStatus } from "./agent";
export type {
  ExtensionSource,
  McpServerInfo,
  McpServerStatus,
  McpToolAccess,
  McpToolInfo,
  McpTransport,
  OfficeToolInfo,
  OfficeToolInstallKind,
  SkillDetail,
  SkillInfo,
} from "./extension";
export type { EventEnvelope, EventSource, EventType } from "./events";
export type { PersonaPresentation, PersonaStyle, WidgetState, WidgetStatusReport } from "./widget";
export type { VrmClipRef, VrmMotionConfig } from "./widget";
export type {
  InteractionKind,
  RiskLevel,
  Task,
  TaskCategory,
  TaskStatus,
  WorkKind,
} from "./task";
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
export type { ChatAttachment, ChatMode, ConversationMessage, MessageRole } from "./conversation";
export type { VoiceProvider, VoiceParams, VoiceSettings } from "./voice";
export type { ArtStyle, AvatarDriver, CharacterConfig, CharacterStyle, MotionFamily } from "./character";
export { DEFAULT_ACTIONS } from "./motions";
export type { ActionSpec, ActionTrigger, FxKind, MotionTable } from "./motions";
export type { RecordingFormat, RecordingMode, RecordingSession } from "./recording";
export type {
  ProjectNode,
  ProjectNodeKind,
  ProjectNodeStatus,
} from "./project";
export type {
  Reminder,
  ReminderKind,
  ReminderRepeat,
  ReminderStatus,
} from "./reminder";
