"""DeskMate 共享契约（pydantic 单一事实源）。

规则：本包是跨模块数据结构的唯一权威定义；
packages/contracts/ts 中的类型是本包的镜像，修改后必须同步并运行一致性测试。
"""

from .agent import AgentInfo, AgentIntegrationStatus
from .approval import ApprovalDecision, ApprovalRequest, ApprovalStatus
from .character import ArtStyle, AvatarDriver, CharacterConfig, CharacterStyle, MotionFamily
from .conversation import ChatMode, Conversation, ConversationMessage, MessageRole
from .events import (
    EventEnvelope,
    EventSource,
    EventType,
    KNOWN_EVENT_TYPES,
    new_event_id,
)
from .extension import (
    ExtensionSource,
    McpServerInfo,
    McpServerStatus,
    McpToolAccess,
    McpToolInfo,
    McpTransport,
    SkillDetail,
    SkillInfo,
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
from .project import (
    ProjectNode,
    ProjectNodeKind,
    ProjectNodeStatus,
    create_project_node_id,
)
from .reminder import Reminder, ReminderKind, ReminderRepeat, ReminderStatus, create_reminder_id
from .recording import RecordingFormat, RecordingMode, RecordingSession
from .task import (
    InteractionKind,
    RiskLevel,
    Task,
    TaskCategory,
    TaskStatus,
    WorkKind,
    create_task_id,
)
from .voice import VoiceParams, VoiceSettings
from .widget import PersonaPresentation, PersonaStyle, WidgetState, WidgetStatusReport

__all__ = [
    "AgentInfo",
    "AgentIntegrationStatus",
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalStatus",
    "ArtStyle",
    "AvatarDriver",
    "CharacterConfig",
    "CharacterStyle",
    "MotionFamily",
    "ChatMode",
    "Conversation",
    "ConversationMessage",
    "CompiledMemory",
    "DocOverview",
    "EventEnvelope",
    "EventSource",
    "EventType",
    "ExtensionSource",
    "KNOWN_EVENT_TYPES",
    "MemoryBlock",
    "MemoryDoc",
    "MemoryEntrySummary",
    "MemorySection",
    "MessageRole",
    "McpServerInfo",
    "McpServerStatus",
    "McpToolAccess",
    "McpToolInfo",
    "McpTransport",
    "RecordingFormat",
    "RecordingMode",
    "RecordingSession",
    "RiskLevel",
    "InteractionKind",
    "SearchHit",
    "ProjectNode",
    "ProjectNodeKind",
    "ProjectNodeStatus",
    "Reminder",
    "ReminderKind",
    "ReminderRepeat",
    "ReminderStatus",
    "SkillDetail",
    "SkillInfo",
    "Task",
    "TaskCategory",
    "TaskStatus",
    "WorkKind",
    "VoiceParams",
    "VoiceSettings",
    "PersonaPresentation",
    "PersonaStyle",
    "WidgetState",
    "WidgetStatusReport",
    "create_task_id",
    "create_project_node_id",
    "create_reminder_id",
    "new_event_id",
]
