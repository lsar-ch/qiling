// 主动提醒契约 —— 镜像自 qiling_contracts/reminder.py。

export type ReminderKind = "memo" | "task";
export type ReminderRepeat = "none" | "daily" | "weekly" | "monthly";
export type ReminderStatus = "pending" | "done" | "cancelled";

export interface Reminder {
  reminder_id: string;
  kind: ReminderKind;
  text: string;
  remind_at: string;
  repeat: ReminderRepeat;
  status: ReminderStatus;
  task_id: string | null;
  created_at: string;
  updated_at: string;
}
