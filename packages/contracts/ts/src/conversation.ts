// 对话契约 —— 镜像自 qiling_contracts/conversation.py。
export type MessageRole = "user" | "assistant" | "system" | "tool";
export type ChatMode = "auto" | "casual" | "work";

export interface ChatAttachment {
  name: string;
  path: string;
  size?: number;
  mime?: string;
}

export interface ConversationMessage {
  id: string;
  role: MessageRole;
  content: string;
  modality: "text" | "voice";
  attachments: ChatAttachment[];
  created_at: string;
}
