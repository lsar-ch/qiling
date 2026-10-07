import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { Reminder, ReminderKind, ReminderRepeat, ReminderStatus } from "@qiling/contracts";
import { confirmText } from "./dialog";
import { createReminder, deleteReminder, fetchReminders, updateReminder } from "./api";

const inputCls =
  "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";
const cardCls = "rounded-lg border border-line bg-white shadow-card p-4 flex flex-col gap-2.5 min-w-0";

const KIND_LABEL: Record<ReminderKind, string> = {
  memo: "备忘录",
  task: "任务",
};

const REPEAT_LABEL: Record<ReminderRepeat, string> = {
  none: "单次",
  daily: "每天",
  weekly: "每周",
  monthly: "每月",
};

const STATUS_META: Record<ReminderStatus, { label: string; cls: string }> = {
  pending: { label: "待办", cls: "bg-brand-100 text-brand" },
  done: { label: "已完成", cls: "bg-ok-50 text-ok" },
  cancelled: { label: "已取消", cls: "bg-surface-tertiary text-muted line-through" },
};

const STATUS_FILTERS: { value: "pending" | "all" | "done" | "cancelled"; label: string }[] = [
  { value: "pending", label: "待办" },
  { value: "all", label: "全部" },
  { value: "done", label: "已完成" },
  { value: "cancelled", label: "已取消" },
];

function fmtTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function sortReminders(list: Reminder[]): Reminder[] {
  return [...list].sort((a, b) => {
    if (a.status === "pending" && b.status !== "pending") return -1;
    if (a.status !== "pending" && b.status === "pending") return 1;
    if (a.status === "pending" && b.status === "pending") {
      return new Date(a.remind_at).getTime() - new Date(b.remind_at).getTime();
    }
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
}

export default function RemindersPage() {
  const [items, setItems] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"pending" | "all" | "done" | "cancelled">("pending");
  const [kindFilter, setKindFilter] = useState<"all" | ReminderKind>("all");
  const [text, setText] = useState("");
  const [kind, setKind] = useState<ReminderKind>("memo");
  const [repeat, setRepeat] = useState<ReminderRepeat>("none");
  const [remindAt, setRemindAt] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async (): Promise<void> => {
    try {
      setItems(await fetchReminders());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载提醒失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (!text.trim() || !remindAt) return;
    setSaving(true);
    try {
      await createReminder({
        kind,
        text: text.trim(),
        remind_at: new Date(remindAt).toISOString(),
        repeat,
      });
      setText("");
      setRemindAt("");
      setRepeat("none");
      setKind("memo");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建提醒失败");
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (id: string, status: ReminderStatus): Promise<void> => {
    try {
      await updateReminder(id, { status });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新提醒失败");
    }
  };

  const remove = async (id: string): Promise<void> => {
    if (!(await confirmText("删除后不可恢复，确定删除这条提醒？"))) return;
    try {
      await deleteReminder(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除提醒失败");
    }
  };

  const visible = useMemo(() => {
    const filtered = items.filter((item) => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (kindFilter !== "all" && item.kind !== kindFilter) return false;
      return true;
    });
    return sortReminders(filtered);
  }, [items, statusFilter, kindFilter]);

  return (
    <div className="flex flex-col gap-5">
      <section className={cardCls}>
        <h2 className="text-sm font-semibold text-ink">新建提醒</h2>
        <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
          <input
            className={inputCls}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="提醒内容，例如：喝水、提交周报"
            maxLength={500}
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value as ReminderKind)}>
              <option value="memo">备忘录</option>
              <option value="task">任务</option>
            </select>
            <select className={inputCls} value={repeat} onChange={(e) => setRepeat(e.target.value as ReminderRepeat)}>
              <option value="none">单次</option>
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
            <input
              type="datetime-local"
              className={inputCls}
              value={remindAt}
              onChange={(e) => setRemindAt(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving || !text.trim() || !remindAt}
              className="px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium disabled:opacity-50"
            >
              {saving ? "创建中…" : "创建提醒"}
            </button>
          </div>
        </form>
      </section>

      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_FILTERS.map((item) => (
          <button
            key={item.value}
            onClick={() => setStatusFilter(item.value)}
            className={`px-3 py-1.5 rounded-full text-xs transition-colors ${
              statusFilter === item.value ? "bg-brand-100 text-brand font-semibold" : "text-ink hover:bg-brand-50"
            }`}
          >
            {item.label}
          </button>
        ))}
        <span className="w-px h-4 bg-line" />
        {(["all", "memo", "task"] as const).map((item) => (
          <button
            key={item}
            onClick={() => setKindFilter(item)}
            className={`px-3 py-1.5 rounded-full text-xs transition-colors ${
              kindFilter === item ? "bg-brand-100 text-brand font-semibold" : "text-ink hover:bg-brand-50"
            }`}
          >
            {item === "all" ? "全部分类" : KIND_LABEL[item]}
          </button>
        ))}
      </div>

      {error && <div className="rounded-lg border border-bad/40 bg-bad-50/40 px-3 py-2 text-sm text-bad">{error}</div>}

      {loading ? (
        <div className="text-sm text-muted">加载中…</div>
      ) : visible.length === 0 ? (
        <div className="rounded-lg border border-line-subtle bg-surface-tertiary px-4 py-10 text-center text-sm text-muted">
          暂无符合条件的提醒
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {visible.map((item) => (
            <article key={item.reminder_id} className={cardCls}>
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-ink leading-relaxed">{item.text}</p>
                <span className={`shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_META[item.status].cls}`}>
                  {STATUS_META[item.status].label}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span>{KIND_LABEL[item.kind]}</span>
                <span>{REPEAT_LABEL[item.repeat]}</span>
                <span>{fmtTime(item.remind_at)}</span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                {item.status === "pending" && (
                  <>
                    <button
                      onClick={() => void setStatus(item.reminder_id, "done")}
                      className="px-2.5 py-1 rounded-md text-xs bg-ok-50 text-ok hover:bg-ok-50/60"
                    >
                      完成
                    </button>
                    <button
                      onClick={() => void setStatus(item.reminder_id, "cancelled")}
                      className="px-2.5 py-1 rounded-md text-xs bg-surface-tertiary text-muted hover:bg-surface-secondary"
                    >
                      取消
                    </button>
                  </>
                )}
                {item.status !== "pending" && (
                  <button
                    onClick={() => void setStatus(item.reminder_id, "pending")}
                    className="px-2.5 py-1 rounded-md text-xs bg-brand-50 text-brand hover:bg-brand-100"
                  >
                    重新激活
                  </button>
                )}
                <button
                  onClick={() => void remove(item.reminder_id)}
                  className="px-2.5 py-1 rounded-md text-xs text-bad hover:bg-bad-50/40"
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
