"""DeskMate 共享契约（pydantic 单一事实源）。

规则：本包是跨模块数据结构的唯一权威定义；
packages/contracts/ts 中的类型是本包的镜像，修改后必须同步并运行一致性测试。
"""

from .agent import AgentInfo, AgentIntegrationStatus
from .approval import ApprovalDecision, ApprovalRequest, ApprovalStatus
from .character import AvatarDriver, CharacterConfig, CharacterStyle
from .conversation import ChatMode, Conversation, ConversationMessage, MessageRole
from .events import (
    EventEnvelope,
    EventSource,
    EventType,
    KNOWN_EVENT_TYPES,
    new_event_id,
)
from .memory import (
    CompiledMemory,
    DocOverview,
    MemoryBlock,
    MemoryDoc,
    MemoryEntrySummary,
    MemorySection,
    SearchHit,
)
from .recording import RecordingFormat, RecordingMode, RecordingSession
from .task import (
    RiskLevel,
    Task,
    TaskCategory,
    TaskStatus,
    create_task_id,
)
from .voice import VoiceParams, VoiceSettings
from .widget import WidgetState, WidgetStatusReport

__all__ = [
    "AgentInfo",
    "AgentIntegrationStatus",
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalStatus",
    "AvatarDriver",
    "CharacterConfig",
    "CharacterStyle",
    "ChatMode",
    "Conversation",
    "ConversationMessage",
    "CompiledMemory",
    "DocOverview",
    "EventEnvelope",
    "EventSource",
    "EventType",
    "KNOWN_EVENT_TYPES",
    "MemoryBlock",
    "MemoryDoc",
    "MemoryEntrySummary",
    "MemorySection",
    "MessageRole",
    "RecordingFormat",
    "RecordingMode",
    "RecordingSession",
    "RiskLevel",
    "SearchHit",
    "Task",
    "TaskCategory",
    "TaskStatus",
    "VoiceParams",
    "VoiceSettings",
    "WidgetState",
    "WidgetStatusReport",
    "create_task_id",
    "new_event_id",
]
