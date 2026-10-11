import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { CompiledMemory, DocOverview, EventEnvelope, MemoryDoc, SearchHit } from "@qiling/contracts";
import type { AgentInfo, AgentIntegrationStatus, Task } from "@qiling/contracts";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { emit, listen } from "@tauri-apps/api/event";
import {
  connectEvents,
  addMemoryEntry,
  deleteMemoryEntry,
  fetchAgents,
  addCustomAgent,
  fetchAgentConfig,
  fetchHealth,
  acquireVoiceLease,
  heartbeatVoiceLease,
  releaseVoiceLease,
  fetchCompiledMemory,
  fetchMemoryDoc,
  fetchMemoryOverview,
  fetchMemoryExport,
  fetchSession,
  fetchTasks,
  markTask,
  fetchTaskRun,
  fetchRuns,
  executeTask,
  cancelRun,
  decideRun,
  type AgentRun,
  type AgentRunMode,
  fetchSettings,
  fetchSetupStatus,
  type SetupStatus,
  routeTask,
  searchMemories,
  searchObsidian,
  fetchMemoryVaultStatus,
  checkObsidianPath,
  fetchWidgetState,
  publishEvent,
  saveMemoryDoc,
  updateSettings,
  updateAgentConfig,
  refreshAgentDetection,
  fetchPersonas,
  type AppSettings,
  type PersonaCard,
  type MemoryVaultStatus,
  type HealthResponse,
  type SessionResponse,
  type WidgetStatusReport,
} from "./api";
import { DEMO_ACTIONS } from "./state";
import ChatPage from "./ChatPage";
import CharacterPage from "./CharacterPage";
import ExtensionsPage from "./ExtensionsPage";
import AboutPage from "./AboutPage";
import MotionLabPage from "./MotionLabPage";
import ModelProfilesSection from "./ModelProfilesSection";
import ProjectNodesPage from "./ProjectNodesPage";
import RemindersPage from "./RemindersPage";
import HomePage from "./HomePage";
import {
  Home,
  MessagesSquare,
  FolderKanban,
  Bell,
  IdCard,
  Brain,
  Library,
  Bot,
  Puzzle,
  Settings,
  Info,
  Globe,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

/** 栖灵标记：与桌面图标同源（陶土底 + 栖枝 + 灵球）。 */
function QilingMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="100 100 824 824" className={className} role="img" aria-label="栖灵">
      <defs>
        <linearGradient id="ql-bg" x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0" stopColor="#a2643f" />
          <stop offset="1" stopColor="#4a2a1a" />
        </linearGradient>
        <radialGradient id="ql-orb" cx="0.38" cy="0.3" r="0.78">
          <stop offset="0" stopColor="#fffbf0" />
          <stop offset="0.42" stopColor="#ffd089" />
          <stop offset="1" stopColor="#e08a2a" />
        </radialGradient>
      </defs>
      <rect x="100" y="100" width="824" height="824" rx="186" fill="url(#ql-bg)" />
      <path
        d="M232 716 C 392 690, 470 612, 566 552 C 636 508, 690 486, 764 480"
        fill="none"
        stroke="#f6eadb"
        strokeWidth="54"
        strokeLinecap="round"
      />
      <circle cx="686" cy="374" r="106" fill="url(#ql-orb)" />
    </svg>
  );
}

type PageKey = "home" | "chat" | "character" | "memory" | "project" | "reminders" | "kb" | "agents" | "extensions" | "settings" | "about" | "motion-lab";

type TaskActionStatus = "running" | "awaiting_approval" | "completed" | "failed";

const TASK_ACTIONS: { status: TaskActionStatus; label: string }[] = [
  { status: "running", label: "执行中" },
  { status: "awaiting_approval", label: "待确认" },
  { status: "completed", label: "完成" },
  { status: "failed", label: "失败" },
];

const AGENT_STATUS_ZH: Record<AgentIntegrationStatus, string> = {
  ready: "可用",
  pending: "预留",
  auth_required: "需凭据",
  not_installed: "未安装",
  error: "异常",
};

const RUN_STATUS_ZH: Record<AgentRun["status"], string> = {
  queued: "排队中",
  running: "运行中",
  awaiting_approval: "待授权",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

// 运行状态徽标：与 KB/Home 的 ok/bad/warn/muted 语义一致；进行中状态用品牌色。
const RUN_STATUS_PILL: Record<AgentRun["status"], string> = {
  queued: "bg-line-subtle text-muted",
  running: "bg-brand-100 text-brand",
  awaiting_approval: "bg-warn-50 text-warn",
  completed: "bg-ok-50 text-ok",
  failed: "bg-bad-50 text-bad",
  cancelled: "bg-surface-tertiary text-muted line-through",
};
const RUN_STATUS_DOT: Record<AgentRun["status"], string> = {
  queued: "bg-muted",
  running: "bg-brand animate-breathe",
  awaiting_approval: "bg-warn animate-pulse",
  completed: "bg-ok",
  failed: "bg-bad",
  cancelled: "bg-muted",
};

// 执行器接入状态：ok=可用、warn=预留待接通、muted=未安装/禁用、bad=异常。
const AGENT_PILL: Record<AgentIntegrationStatus, { pill: string; dot: string; note: string; noteCls: string }> = {
  ready: { pill: "bg-ok-50 text-ok", dot: "bg-ok", note: "已接通真实执行，可直接运行任务。", noteCls: "text-ok" },
  pending: { pill: "bg-warn-50 text-warn", dot: "bg-warn", note: "执行器已预留，完成接入配置后即可用。", noteCls: "text-warn" },
  auth_required: { pill: "bg-warn-50 text-warn", dot: "bg-warn animate-pulse", note: "已安装但没有可用凭据：自备 API Key（需付费订阅）后测试连接。", noteCls: "text-warn" },
  not_installed: { pill: "bg-line-subtle text-muted", dot: "bg-muted", note: "尚未安装；按文档安装后刷新即可使用。", noteCls: "text-muted" },
  error: { pill: "bg-bad-50 text-bad", dot: "bg-bad", note: "接入异常，请检查配置后刷新。", noteCls: "text-bad" },
};
const AGENT_CARD_CLS: Record<AgentIntegrationStatus, string> = {
  ready: "border-line bg-surface",
  pending: "border-warn/40 bg-warn-50/40",
  auth_required: "border-warn/40 bg-warn-50/40",
  not_installed: "border-line-subtle bg-surface-tertiary",
  error: "border-bad/40 bg-bad-50/40",
};
// 手动停用的执行器：仍然展示，但不参与任务执行。
const AGENT_DISABLED_PILL = {
  pill: "bg-line-subtle text-muted",
  dot: "bg-muted",
  note: "已停用：不参与任务执行，需要时重新启用即可。",
  noteCls: "text-muted",
};

type NavItem = { key: PageKey; icon: LucideIcon };

const NAV: NavItem[] = [
  { key: "home", icon: Home },
  { key: "chat", icon: MessagesSquare },
  { key: "project", icon: FolderKanban },
  { key: "reminders", icon: Bell },
  { key: "character", icon: IdCard },
  { key: "memory", icon: Brain },
  { key: "kb", icon: Library },
  { key: "agents", icon: Bot },
  { key: "extensions", icon: Puzzle },
  { key: "settings", icon: Settings },
  { key: "about", icon: Info },
];

const NAV_GROUPS: { items: PageKey[] }[] = [
  { items: ["home"] },
  { items: ["chat", "project", "reminders"] },
  { items: ["character", "memory", "kb"] },
  { items: ["agents", "extensions"] },
  { items: ["settings", "about"] },
];

/** 不在主导航显示的开发者页面，仅通过 `#/motion-lab` 直达。 */
const HIDDEN_PAGES: ReadonlySet<PageKey> = new Set(["motion-lab"]);

/** URL 片段 → 页面：`#/chat` → chat，未知或缺失回落主页。 */
function pageFromHash(hash: string): PageKey {
  const key = hash.replace(/^#\/?/, "");
  if (NAV.some((item) => item.key === key) || HIDDEN_PAGES.has(key as PageKey)) {
    return key as PageKey;
  }
  return "home";
}

/**
 * 页面状态与 URL 片段双向同步（WP-02）。
 * 挂件用 `open_main_ui(page="chat")` 打开带片段的 URL，这里据此直接落到目标页。
 */
function useHashPage(): [PageKey, (key: PageKey) => void] {
  const [page, setPage] = useState<PageKey>(() => pageFromHash(window.location.hash));

  useEffect(() => {
    const sync = (): void => setPage(pageFromHash(window.location.hash));
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const navigate = useCallback((key: PageKey) => {
    if (window.location.hash !== `#/${key}`) {
      window.location.hash = `#/${key}`;
    }
    setPage(key);
  }, []);

  return [page, navigate];
}

function eventToState(eventType: string): string | null {
  const map: Record<string, string> = {
    "speech.started": "listening",
    "conversation.input": "thinking",
    "conversation.transcript": "thinking",
    "conversation.response": "speaking",
    "task.started": "executing",
    "task.progress": "executing",
    "task.approval_required": "awaiting_approval",
    "speech.interrupted": "interrupted",
    "task.completed": "completed",
    "task.failed": "completed",
    "task.cancelled": "completed",
    "task.approval_reminder": "awaiting_approval",
    "task.timed_out": "completed",
  };
  return map[eventType] ?? null;
}

function fmtUptime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

function HighlightMatch({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLowerCase();
  if (!needle) return <>{text}</>;
  const lower = text.toLowerCase();
  const out: ReactNode[] = [];
  let from = 0;
  let hits = 0;
  let idx = lower.indexOf(needle, from);
  while (idx !== -1 && hits < 30) {
    if (idx > from) out.push(text.slice(from, idx));
    out.push(
      <mark key={`${idx}-${hits}`} className="rounded bg-brand-100 text-ink px-0.5">
        {text.slice(idx, idx + needle.length)}
      </mark>
    );
    from = idx + needle.length;
    hits += 1;
    idx = lower.indexOf(needle, from);
  }
  out.push(text.slice(from));
  return <>{out}</>;
}

function KnowledgeBasePage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draftPath, setDraftPath] = useState("");
  const [vault, setVault] = useState<MemoryVaultStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ available: boolean; path: string; items: { path: string; title: string; matches: string[] }[] } | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [searchedQuery, setSearchedQuery] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<{ available: boolean; note_count: number } | null>(null);

  useEffect(() => {
    void fetchSettings()
      .then((s) => {
        setSettings(s);
        setDraftPath(s.memory.obsidian_vault_path);
      })
      .catch(() => setError("设置加载失败"));
    void fetchMemoryVaultStatus().then(setVault).catch(() => setVault(null));
  }, []);

  const linked = settings?.memory.mode === "obsidian_linked";
  const vaultConfigured = Boolean(vault?.available);

  const reloadVaultStatus = async (): Promise<void> => {
    try {
      setVault(await fetchMemoryVaultStatus());
    } catch {
      setVault(null);
    }
  };

  const enableVault = async (): Promise<void> => {
    const path = draftPath.trim();
    if (!path) {
      setError("请先填写库路径（可留空稍后再配，填了即启用检索与自动归档）。");
      return;
    }
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const next = await updateSettings({ memory_mode: "obsidian_linked", obsidian_vault_path: path });
      setSettings(next);
      setNotice("已启用本地仓库：保存后记忆页会把记忆自动归档到库内独立目录。");
      await reloadVaultStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "启用失败");
    } finally {
      setSaving(false);
    }
  };

  const disableVault = async (): Promise<void> => {
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const next = await updateSettings({ memory_mode: "standalone" });
      setSettings(next);
      setNotice("已断开本地仓库；记忆继续保存在本机。路径输入已保留，随时可重新启用。");
      await reloadVaultStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开失败");
    } finally {
      setSaving(false);
    }
  };

  const checkPath = async (): Promise<void> => {
    const path = draftPath.trim();
    if (!path) {
      setError("请先填写 Obsidian 库路径。");
      return;
    }
    setChecking(true);
    setNotice("");
    setError("");
    setCheckResult(null);
    try {
      const checked = await checkObsidianPath(path);
      setCheckResult({ available: checked.available, note_count: checked.note_count });
    } catch (e) {
      setError(e instanceof Error ? e.message : "路径检测失败");
    } finally {
      setChecking(false);
    }
  };

  const resetObsidianPath = (): void => {
    if (!settings?.memory.obsidian_default_path) return;
    setDraftPath(settings.memory.obsidian_default_path);
    setNotice("");
    setError("");
    setCheckResult(null);
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError("");
    setSearchedQuery(query.trim());
    try {
      const res = await searchObsidian(query.trim());
      setResults(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "搜索失败");
      setResults(null);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Vault config card */}
      <div className="rounded-lg border border-line bg-surface shadow-card">
        <div className="px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-ink">Obsidian 知识库</h3>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${linked ? "bg-ok-50 text-ok" : "bg-warn-50 text-warn"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${linked ? "bg-ok" : "bg-warn"}`} />
              {linked ? "已启用" : "未启用"}
            </span>
          </div>
          <p className="text-xs text-muted leading-relaxed mb-3">
            库路径可填可不填。启用后，记忆页会把本地记忆自动归档到该库的 <code className="font-mono">栖灵/记忆</code> 独立目录，不影响库内其它内容；记忆本体仍保存在本机。
          </p>
          <label className="flex flex-col gap-1.5 text-xs text-muted mb-3">
            <span>库路径</span>
            <input
              className="w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
              value={draftPath}
              onChange={(e) => {
                setDraftPath(e.target.value);
                setCheckResult(null);
              }}
              placeholder="/Users/.../knowledge"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              className="h-[38px] px-3 rounded-lg border border-line text-sm text-ink hover:bg-surface-secondary transition-colors disabled:opacity-50"
              onClick={() => void checkPath()}
              disabled={saving || checking}
            >
              {checking ? "检测中…" : "检测路径"}
            </button>
            {settings?.memory.obsidian_default_path && draftPath !== settings.memory.obsidian_default_path && (
              <button
                className="h-[38px] px-3 rounded-lg border border-line text-sm text-muted hover:text-ink transition-colors disabled:opacity-50"
                onClick={resetObsidianPath}
                disabled={saving || checking}
              >
                恢复默认
              </button>
            )}
            {!linked ? (
              <button
                className="h-[38px] px-4 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                onClick={() => void enableVault()}
                disabled={saving}
              >
                {saving ? "启用中…" : "保存并启用"}
              </button>
            ) : (
              <>
                <button
                  className="h-[38px] px-4 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                  onClick={() => void enableVault()}
                  disabled={saving}
                >
                  {saving ? "保存中…" : "保存路径"}
                </button>
                <button
                  className="h-[38px] px-4 rounded-lg border border-line bg-surface-tertiary text-sm text-ink hover:border-bad hover:text-bad transition-colors disabled:opacity-50"
                  onClick={() => void disableVault()}
                  disabled={saving}
                >
                  断开
                </button>
              </>
            )}
          </div>
          {notice && <p className="text-xs text-ok mt-2.5 leading-relaxed">{notice}</p>}
          {checkResult && !checkResult.available && (
            <p className="text-xs text-bad mt-2.5 leading-relaxed">路径不可访问：请检查拼写、权限或是否已下载到本地。</p>
          )}
          {checkResult?.available && (
            <p className="text-xs text-ok mt-2.5 leading-relaxed">路径可用，检测到 {checkResult.note_count} 篇 Markdown 笔记。启用后才开始自动归档。</p>
          )}
          {linked && vault && !vault.available && (
            <p className="text-xs text-warn mt-2.5 leading-relaxed">当前路径不可访问或未启用：检索暂不可用。记忆仍保存在本机，可保留该路径稍后修正。</p>
          )}
          {linked && vault?.available && (
            <p className="flex items-center gap-1.5 text-[11px] text-muted mt-2.5 leading-relaxed min-w-0">
              {vault.mirror_dir_exists ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-ok shrink-0" />
                  <span className="min-w-0">自动归档已就绪：库内 <code className="font-mono">栖灵/记忆</code> 共 {vault.doc_files} 份文档
                    {vault.last_sync ? ` · 上次同步 ${new Date(vault.last_sync).toLocaleString("zh-CN", { hour12: false })}` : ""}
                  </span>
                </>
              ) : (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-warn shrink-0" />
                  <span className="min-w-0">仓库可用，归档目录尚未生成；保存后首次记忆变更会创建。</span>
                </>
              )}
            </p>
          )}
        </div>
      </div>

      {/* Search bar */}
      <div className="rounded-lg border border-line bg-surface shadow-card">
        <div className="px-5 py-4">
          <h3 className="text-sm font-semibold text-ink mb-3">全文检索</h3>
          <div className="flex items-center gap-2.5">
            <input
              className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入关键词搜索知识库…"
              onKeyDown={(e) => { if (e.key === "Enter") void runSearch(); }}
              disabled={!vaultConfigured}
            />
            <button
              className="h-[38px] px-4 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50 disabled:cursor-default"
              onClick={() => void runSearch()}
              disabled={searching || !query.trim() || !vaultConfigured}
            >
              {searching ? "搜索中…" : "搜索"}
            </button>
          </div>
          {!vaultConfigured ? (
            <p className="text-xs text-warn mt-2 leading-relaxed">
              尚未连接可用的本地仓库，搜索暂不可用。在上方填写库路径并点「保存并启用」后即可检索。
            </p>
          ) : searching ? (
            <p className="text-xs text-brand mt-2 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-brand animate-breathe" />
              正在检索本地笔记…
            </p>
          ) : !results && !error ? (
            <p className="text-xs text-muted mt-2">输入关键词后回车或点击「搜索」，即可检索本地笔记。</p>
          ) : null}
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm">{error}</div>
      )}

      {/* Results */}
      {results && !error && (
        <div className="rounded-lg border border-line bg-surface shadow-card">
          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-ink">搜索结果</h3>
              {results.available && (
                <span className="text-xs text-muted">「{searchedQuery}」· {results.items.length} 条匹配</span>
              )}
            </div>
            {!results.available ? (
              <div className="rounded-lg bg-warn-50 text-warn px-4 py-3.5 text-sm leading-relaxed">
                Obsidian 检索暂不可用：当前未启用「obsidian_linked」记忆模式，或库路径无效。
                <code className="mt-1.5 block text-xs font-mono break-anywhere">{results.path || "（路径为空）"}</code>
                请在上方检查库路径与启用状态后重试。
              </div>
            ) : results.items.length === 0 ? (
              <div className="border border-dashed border-line rounded-lg px-6 py-8 text-center">
                <p className="text-sm text-muted">未找到与「{searchedQuery}」匹配的内容。</p>
                <p className="text-xs text-muted mt-1.5">尝试更换关键词，或确认 Obsidian 库路径后重试。</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {results.items.map((item, i) => (
                  <div key={`${item.path}-${i}`} className="border border-line-subtle rounded-lg p-3.5 hover:border-line transition-colors min-w-0">
                    <div className="flex items-start justify-between gap-3 mb-1.5 min-w-0">
                      <h4 className="flex-1 min-w-0 text-sm font-medium text-ink leading-snug break-anywhere">{item.title || item.path}</h4>
                      <code className="text-[11px] font-mono text-muted bg-surface-tertiary px-1.5 py-0.5 rounded shrink-0 truncate max-w-[40%]" title={item.path}>{item.path}</code>
                    </div>
                    {item.matches.length > 0 && (
                      <div className="flex flex-col gap-1.5 mt-2">
                        {item.matches.map((m, j) => (
                          <p key={j} className="text-xs text-muted leading-relaxed pl-2 border-l-2 border-brand-200 break-anywhere min-w-0">
                            <HighlightMatch text={m} query={searchedQuery} />
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Info section */}
      <div className="rounded-lg border border-line bg-surface-tertiary px-5 py-3.5">
        <p className="text-xs text-muted leading-relaxed">
          知识库当前仅支持 Obsidian 只读检索与记忆自动归档。写入、授权和更多知识库功能将在后续版本中接入。记忆页面也包含本地搜索入口。
        </p>
      </div>
    </div>
  );
}

function MemoryPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [overview, setOverview] = useState<DocOverview[]>([]);
  const [selected, setSelected] = useState<{ layer: string; key: string } | null>(null);
  const [doc, setDoc] = useState<MemoryDoc | null>(null);
  const [compiled, setCompiled] = useState<CompiledMemory | null>(null);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [obsidianQuery, setObsidianQuery] = useState("");
  const [obsidian, setObsidian] = useState<{ available: boolean; path: string; items: { path: string; title: string; matches: string[] }[] }>({ available: false, path: "", items: [] });
  const [obsidianSearched, setObsidianSearched] = useState(false);
  const [status, setStatus] = useState("");
  const [exporting, setExporting] = useState(false);
  const [entry, setEntry] = useState({ section: "", text: "" });
  const [vaultStatus, setVaultStatus] = useState<MemoryVaultStatus | null>(null);

  const reload = async (): Promise<void> => {
    const [nextSettings, items, compiledDoc] = await Promise.all([
      fetchSettings(),
      fetchMemoryOverview(),
      fetchCompiledMemory(),
    ]);
    setSettings(nextSettings);
    setOverview(items);
    setCompiled(compiledDoc);
    if (!selected && items.length) {
      setSelected({ layer: items[0].layer, key: items[0].key });
    }
  };

  useEffect(() => {
    void reload().catch((e) => setStatus(e instanceof Error ? e.message : "记忆加载失败"));
  }, []);

  useEffect(() => {
    void fetchMemoryVaultStatus()
      .then(setVaultStatus)
      .catch(() => setVaultStatus(null));
  }, []);

  useEffect(() => {
    if (!selected) return;
    void fetchMemoryDoc(selected.layer, selected.key)
      .then(setDoc)
      .catch((e) => setStatus(e instanceof Error ? e.message : "文档加载失败"));
  }, [selected]);

  const save = async (): Promise<void> => {
    if (!selected || !doc) return;
    const next = await saveMemoryDoc(selected.layer, selected.key, doc.raw_markdown);
    setDoc(next);
    await reload();
    setStatus("已保存");
  };

  const addEntry = async (): Promise<void> => {
    if (!selected) return;
    const text = entry.text.trim();
    if (!text) return;
    const next = await addMemoryEntry(selected.layer, selected.key, entry.section.trim() || "项目进度", text);
    setDoc(next);
    setEntry({ section: "", text: "" });
    await reload();
  };

  const runSearch = async (): Promise<void> => {
    if (!search.trim()) return;
    setSearched(true);
    try {
      setResults(await searchMemories(search));
    } catch (e) {
      setResults([]);
      setStatus(e instanceof Error ? `记忆检索失败：${e.message}` : "记忆检索失败");
    }
  };

  const runObsidianSearch = async (): Promise<void> => {
    if (!obsidianQuery.trim()) return;
    setObsidianSearched(true);
    try {
      setObsidian(await searchObsidian(obsidianQuery));
    } catch (e) {
      setObsidian({ available: false, path: obsidian.path, items: [] });
      setStatus(e instanceof Error ? `Obsidian 检索失败：${e.message}` : "Obsidian 检索失败");
    }
  };

  const exportMemory = async (): Promise<void> => {
    setExporting(true);
    try {
      const bundle = await fetchMemoryExport();
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `qiling-memory-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus("已导出记忆包");
    } finally {
      setExporting(false);
    }
  };

  const memMode = settings?.memory.mode ?? null;
  const vaultConfigured = Boolean(settings?.memory.obsidian_configured && settings?.memory.obsidian_vault_path.trim());
  const obsidianChip =
    memMode === "obsidian_linked"
      ? vaultConfigured
        ? { label: "已连接", cls: "bg-ok-50 text-ok", dot: "bg-ok" }
        : { label: "未配置", cls: "bg-warn-50 text-warn", dot: "bg-warn" }
      : memMode === "export_import"
        ? { label: "本地档案", cls: "bg-warn-50 text-warn", dot: "bg-warn" }
        : memMode === "standalone"
          ? { label: "未启用", cls: "bg-line-subtle text-muted", dot: "bg-muted" }
          : null;
  const MEMORY_GROUPS: { layer: DocOverview["layer"]; title: string; hint: string }[] = [
    { layer: "L3", title: "L3 · 画像层", hint: "跨场景长期结论：用户画像、偏好、项目进度、近期上下文" },
    { layer: "L2", title: "L2 · 场景事实", hint: "按对话、任务、知识库、项目、角色互动归纳" },
    { layer: "persona", title: "角色档案", hint: "角色独立人设，不混入用户画像" },
  ];

  return (
    <section className="flex flex-col gap-3.5">
      {/* Top grid: list + editor */}
      <div className="grid grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)] gap-3.5">
        {/* Memory list */}
        <section className="rounded-lg border border-line bg-surface shadow-card p-4 min-w-0">
          <div className="flex items-center justify-between gap-2.5 mb-1.5">
            <h3 className="text-sm font-semibold text-ink">记忆概览</h3>
            <button className="text-brand text-xs hover:underline" onClick={() => void reload()}>刷新</button>
          </div>
          <p className="text-[11px] text-muted leading-relaxed mb-2.5">L1 事件留痕自动归档；此处管理 L2 场景事实、L3 画像与角色档案。</p>
          {overview.length === 0 ? (
            <p className="text-xs text-muted leading-relaxed py-6 text-center">暂无记忆文档。对话、任务与知识库检索会自动沉淀记忆。</p>
          ) : (
            <div className="flex flex-col gap-3 max-h-[560px] overflow-auto scroll-thin pr-1">
              {MEMORY_GROUPS.map((group) => {
                const items = overview.filter((item) => item.layer === group.layer);
                if (items.length === 0) return null;
                return (
                  <div key={group.layer} className="flex flex-col gap-1.5 min-w-0">
                    <div className="px-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-semibold text-ink">{group.title}</span>
                        <span className="text-[10px] text-muted">{items.length} 份</span>
                      </div>
                      <p className="text-[10px] text-muted leading-relaxed mt-0.5">{group.hint}</p>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {items.map((item) => (
                        <button
                          key={`${item.layer}:${item.key}`}
                          className={`grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-0.5 p-2.5 rounded-lg border text-left transition-colors min-w-0 ${
                            selected?.layer === item.layer && selected?.key === item.key
                              ? "border-brand bg-brand-50"
                              : "border-line hover:border-brand hover:bg-brand-50"
                          }`}
                          onClick={() => setSelected({ layer: item.layer, key: item.key })}
                        >
                          <b className="truncate text-[13px] text-ink" title={item.title}>{item.title}</b>
                          <span className="row-span-2 col-start-2 self-center rounded-full bg-surface-tertiary px-2 py-0.5 text-[10px] text-muted whitespace-nowrap">{item.entry_count} 条</span>
                          <code className="truncate text-[10px] text-muted font-mono" title={`${item.layer}/${item.key}`}>{item.key}</code>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Editor */}
        <section className="rounded-lg border border-line bg-surface shadow-card p-4 min-w-0">
          <div className="flex items-center justify-between gap-2.5 mb-3">
            <h3 className="text-sm font-semibold text-ink min-w-0 break-anywhere">{selected ? `${selected.layer}/${selected.key}` : "未选择记忆"}</h3>
            <div className="flex items-center gap-2 shrink-0 min-w-0">
              <input className="w-24 border border-line rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand" value={entry.section} onChange={(event) => setEntry((current) => ({ ...current, section: event.target.value }))} placeholder="小节名称" aria-label="小节名称" />
              <input className="w-36 border border-line rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand" value={entry.text} onChange={(event) => setEntry((current) => ({ ...current, text: event.target.value }))} placeholder="记忆内容" aria-label="记忆内容" />
              <button className="text-brand text-xs hover:underline whitespace-nowrap" onClick={() => void addEntry()}>新增条目</button>
              <button className="text-brand text-xs hover:underline whitespace-nowrap" onClick={() => void save()}>保存文档</button>
            </div>
          </div>
          {doc ? (
            <>
              <textarea
                className="w-full min-h-[220px] border border-line rounded-lg p-3 text-sm font-mono leading-relaxed focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20 resize-y"
                value={doc.raw_markdown}
                onChange={(e) => setDoc({ ...doc, raw_markdown: e.target.value })}
              />
              <div className="flex flex-col gap-2.5 mt-3">
                {doc.sections.map((section) => (
                  <div key={section.title} className="border-t border-line pt-2.5">
                    <h4 className="text-[13px] font-semibold text-ink mb-2">{section.title}</h4>
                    {section.entries.map((entry) => (
                      <div key={entry.entry_id} className="flex items-start justify-between gap-2 py-1.5">
                        <div>
                          <b className="text-[13px] leading-relaxed break-words">{entry.text}</b>
                          <div className="text-[11px] text-muted">{entry.refs.join(" · ") || "无引用"}</div>
                        </div>
                        <button className="border border-line bg-surface rounded-lg px-2 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors shrink-0" onClick={async () => {
                          await deleteMemoryEntry(entry.entry_id);
                          if (selected) setDoc(await fetchMemoryDoc(selected.layer, selected.key));
                          await reload();
                        }}>删除</button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="border border-dashed border-line rounded-lg px-4 py-10 text-center">
              <p className="text-sm text-muted">未选择文档</p>
              <p className="text-xs text-muted mt-1">从左侧「记忆概览」选择 L2 / L3 / 角色档案进行查看与编辑。</p>
            </div>
          )}
          {status && <p className={`mt-2.5 text-[13px] ${status.includes("失败") ? "text-bad" : "text-ok"}`}>{status}</p>}
        </section>
      </div>

      {/* Bottom tools grid */}
      <section className="rounded-lg border border-line bg-surface shadow-card p-4 grid grid-cols-1 md:grid-cols-3 gap-3.5">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink mb-2.5">记忆检索</h3>
          <div className="flex gap-2 items-center">
            <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="输入关键词" />
            <button className="h-[38px] px-3.5 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors" onClick={() => void runSearch()}>搜索</button>
          </div>
          {results.length > 0 && (
            <p className="text-[11px] text-muted mt-2.5">「{search.trim()}」共 {results.length} 条命中</p>
          )}
          {searched && results.length === 0 && (
            <div className="border border-dashed border-line rounded-lg px-4 py-5 text-center mt-2.5">
              <p className="text-xs text-muted">未找到「{search.trim()}」的匹配条目</p>
              <p className="text-[11px] text-muted mt-1">可尝试更换关键词，或先确认「注入内容」覆盖的记忆范围。</p>
            </div>
          )}
          {results.map((hit) => (
            <div key={hit.entry_id} className="border border-line rounded-lg p-2.5 mt-2 min-w-0">
              <p className="text-[13px] leading-relaxed break-anywhere"><HighlightMatch text={hit.text} query={search} /></p>
              <span className="block text-[11px] text-muted mt-1 break-anywhere">{hit.layer}/{hit.key} · {hit.section}</span>
            </div>
          ))}
        </div>

        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink mb-2.5">注入内容</h3>
          <pre className="max-h-[210px] overflow-auto border border-line rounded-lg p-3 text-xs font-mono leading-relaxed bg-surface-tertiary whitespace-pre-wrap break-words">{compiled?.text || "无可注入内容"}</pre>
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2.5">
            <h3 className="text-sm font-semibold text-ink">Obsidian 只读检索</h3>
            {obsidianChip && (
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${obsidianChip.cls}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${obsidianChip.dot}`} />
                {obsidianChip.label}
              </span>
            )}
          </div>
          {memMode === "standalone" && (
            <div className="rounded-lg bg-surface-tertiary text-muted px-3 py-2.5 text-xs leading-relaxed">
              当前为「独立本地」模式：记忆保存在本机。可到「知识库」页填写库路径并启用，启用后记忆会自动归档到库内独立目录。
            </div>
          )}
          {memMode === "export_import" && (
            <div className="flex flex-col gap-2">
              <div className="rounded-lg bg-warn-50 text-warn px-3 py-2.5 text-xs leading-relaxed">导入导出模式仅使用本地档案，可导出记忆包；导入向导将在后续版本补充。</div>
              <button className="h-[38px] self-start px-3.5 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50" onClick={() => void exportMemory()} disabled={exporting}>{exporting ? "导出中…" : "导出记忆包"}</button>
            </div>
          )}
          {memMode === "obsidian_linked" && vaultConfigured && (
            <>
              <div className="flex gap-2 items-center">
                <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={obsidianQuery} onChange={(e) => setObsidianQuery(e.target.value)} placeholder="搜索知识库" />
                <button className="h-[38px] px-3.5 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors" onClick={() => void runObsidianSearch()}>搜索</button>
              </div>
              <p className="flex items-center gap-1.5 text-[11px] text-muted mt-1.5 min-w-0">
                <span className="w-1.5 h-1.5 rounded-full bg-ok shrink-0" />
                <span className="shrink-0">Vault</span>
                <code className="font-mono truncate max-w-full break-all" title={settings?.memory.obsidian_vault_path}>{settings?.memory.obsidian_vault_path}</code>
              </p>
              {vaultStatus && (
                vaultStatus.mirror_dir_exists ? (
                  <p className="flex items-start gap-1.5 text-[11px] text-muted mt-1.5 leading-relaxed min-w-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-ok shrink-0 mt-1" />
                    <span className="min-w-0">已连接本地仓库：记忆自动归档到 <code className="font-mono">栖灵/记忆</code>（{vaultStatus.doc_files} 份文档
                      {vaultStatus.last_sync ? ` · 上次同步 ${new Date(vaultStatus.last_sync).toLocaleString("zh-CN", { hour12: false })}` : ""}）。</span>
                  </p>
                ) : (
                  <p className="flex items-start gap-1.5 text-[11px] text-muted mt-1.5 leading-relaxed min-w-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-warn shrink-0 mt-1" />
                    <span className="min-w-0">仓库已连接，归档目录尚未生成；本地记忆变更后会自动创建。</span>
                  </p>
                )
              )}
              {obsidianSearched && obsidian.items.length === 0 && (
                <p className="text-xs text-muted mt-2.5">未找到「{obsidianQuery.trim()}」的匹配笔记。</p>
              )}
              {obsidian.items.map((item) => (
                <div key={item.path} className="border border-line rounded-lg p-2.5 mt-2 min-w-0">
                  <b className="block text-[13px] leading-relaxed break-anywhere">{item.title || item.path}</b>
                  <span className="block text-[11px] text-muted mt-1 break-anywhere">{item.path}</span>
                  {item.matches.slice(0, 2).map((match, i) => (
                    <p key={i} className="text-[11px] text-muted leading-relaxed mt-1 break-anywhere">{match}</p>
                  ))}
                </div>
              ))}
            </>
          )}
          {memMode === "obsidian_linked" && !vaultConfigured && (
            <div className="rounded-lg bg-warn-50 text-warn px-3 py-2.5 text-xs leading-relaxed">
              已选择「Obsidian 连接」但 vault 尚未配置或路径不可访问；请到「知识库」页检查库路径与启用状态。
            </div>
          )}
          {memMode === null && <p className="text-[11px] text-muted">正在读取记忆模式…</p>}
        </div>
      </section>
    </section>
  );
}

function MyAgentsPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<Record<string, AgentRun>>({});
  const [input, setInput] = useState("");
  const [routing, setRouting] = useState<{ task: Task | null; status: string }>({ task: null, status: "" });
  const [loading, setLoading] = useState(false);
  const [taskNotice, setTaskNotice] = useState("");
  const [taskError, setTaskError] = useState("");
  const [busyTask, setBusyTask] = useState<{ taskId: string; status: TaskActionStatus } | null>(null);
  const [busyRun, setBusyRun] = useState("");
  const [runModes, setRunModes] = useState<Record<string, AgentRunMode>>({});
  const [agentItems, setAgentItems] = useState<AgentInfo[]>([]);
  const [defaultExecutor, setDefaultExecutor] = useState("");
  const [agentLoading, setAgentLoading] = useState(true);
  const [agentError, setAgentError] = useState("");
  const [configName, setConfigName] = useState<string | null>(null);
  const [configCommand, setConfigCommand] = useState("");
  const [configApiKey, setConfigApiKey] = useState("");
  const [configKeyConfigured, setConfigKeyConfigured] = useState(false);
  const [configKeyEnv, setConfigKeyEnv] = useState("");
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customCommand, setCustomCommand] = useState("");
  const [customKeyEnv, setCustomKeyEnv] = useState("");
  const [customKey, setCustomKey] = useState("");
  const [customBusy, setCustomBusy] = useState(false);
  const [customError, setCustomError] = useState("");
  const [configLoginHint, setConfigLoginHint] = useState("");
  const [configSignupUrl, setConfigSignupUrl] = useState("");
  const [keyTesting, setKeyTesting] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configNotice, setConfigNotice] = useState("");
  const [flagBusy, setFlagBusy] = useState("");
  const [flagNotice, setFlagNotice] = useState("");
  const [flagError, setFlagError] = useState("");

  const loadAgents = async (): Promise<void> => {
    setAgentLoading(true);
    setAgentError("");
    try {
      const data = await fetchAgents();
      // 已启用的排前面：页面先给「在用的」，再给「可添加的」
      setAgentItems(
        [...data.items].sort((a, b) => Number(b.enabled) - Number(a.enabled)),
      );
      setDefaultExecutor(data.default_executor);
    } catch (e) {
      setAgentError(e instanceof Error ? `执行器状态获取失败：${e.message}` : "执行器状态获取失败");
    } finally {
      setAgentLoading(false);
    }
  };

  const setExecutorFlag = async (
    name: string,
    body: { enabled?: boolean; set_default?: boolean },
    notice: string,
  ): Promise<void> => {
    if (flagBusy) return;
    setFlagBusy(name);
    setFlagNotice("");
    setFlagError("");
    try {
      await updateAgentConfig(name, body);
      setFlagNotice(notice);
      await loadAgents();
    } catch (e) {
      setFlagError(e instanceof Error ? e.message : "执行器状态更新失败");
    } finally {
      setFlagBusy("");
    }
  };

  const submitCustomAgent = async (): Promise<void> => {
    if (customBusy) return;
    setCustomBusy(true);
    setCustomError("");
    try {
      await addCustomAgent({
        name: customName.trim(),
        command: customCommand.trim(),
        api_key_env: customKeyEnv.trim() || null,
        api_key: customKey.trim() || null,
      });
      setFlagNotice(`已添加执行器 ${customName.trim()}。`);
      setCustomName("");
      setCustomCommand("");
      setCustomKeyEnv("");
      setCustomKey("");
      setCustomOpen(false);
      await loadAgents();
    } catch (e) {
      setCustomError(e instanceof Error ? e.message : "添加失败");
    } finally {
      setCustomBusy(false);
    }
  };

  const openAgentConfig = async (name: string): Promise<void> => {
    setConfigName(name);
    setConfigCommand("");
    setConfigApiKey("");
    setConfigKeyConfigured(false);
    setConfigKeyEnv("");
    setConfigLoginHint("");
    setConfigSignupUrl("");
    setConfigError("");
    setConfigNotice("");
    try {
      const data = await fetchAgentConfig();
      const entry = data.items.find((item) => item.name === name);
      const value = entry?.config?.[`${name}_command`] ?? entry?.config?.acp_command;
      setConfigCommand(typeof value === "string" ? value : "");
      setConfigKeyConfigured(Boolean(entry?.api_key_configured));
      const keyEnv = entry?.config?.api_key_env;
      setConfigKeyEnv(typeof keyEnv === "string" ? keyEnv : "");
      const hint = entry?.config?.login_hint;
      setConfigLoginHint(typeof hint === "string" ? hint : "");
      const signup = entry?.config?.signup_url;
      setConfigSignupUrl(typeof signup === "string" ? signup : "");
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "配置读取失败");
    }
  };

  const closeAgentConfig = (): void => {
    setConfigName(null);
    setConfigCommand("");
    setConfigApiKey("");
    setConfigKeyConfigured(false);
    setConfigKeyEnv("");
    setConfigLoginHint("");
    setConfigSignupUrl("");
    setConfigError("");
    setConfigNotice("");
  };

  const saveAgentConfig = async (name: string, commandOverride?: string | null): Promise<void> => {
    const command = commandOverride !== undefined ? commandOverride : configCommand.trim() || null;
    // 只发送本次真正填写的 key：空串会清掉服务端已存的凭据，不能因为没动输入框就误清。
    const typedKey = configApiKey.trim();
    const body: { command: string | null; api_key?: string } = { command };
    const supportsKey = name === "workbuddy" || Boolean(configKeyEnv);
    if (supportsKey && commandOverride === undefined && typedKey) {
      body.api_key = typedKey;
    }
    setConfigSaving(true);
    setConfigError("");
    setConfigNotice("");
    try {
      const updated = await updateAgentConfig(name, body);
      setConfigNotice(command ? "已保存手动路径。" : "已恢复自动检测。");
      if (updated.integration_status === "not_installed") {
        setConfigError(command ? `路径已保存，但该路径不可用：${command}` : `自动检测未找到 ${name}。`);
      }
      closeAgentConfig();
      await loadAgents();
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "配置保存失败");
    } finally {
      setConfigSaving(false);
    }
  };

  const clearAgentKey = async (name: string): Promise<void> => {
    setConfigSaving(true);
    setConfigError("");
    setConfigNotice("");
    try {
      await updateAgentConfig(name, { api_key: "" });
      setConfigApiKey("");
      setConfigKeyConfigured(false);
      setConfigNotice("已清除 API Key，将回落到系统环境里的同名变量。");
      await loadAgents();
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "清除失败");
    } finally {
      setConfigSaving(false);
    }
  };

  // 通用 ACP 执行器测试：握手探测成本低，一次刷新就能给结论。
  const testAgentConnection = async (name: string): Promise<void> => {
    setKeyTesting(true);
    setConfigError("");
    setConfigNotice("");
    try {
      const typedKey = configApiKey.trim();
      if (typedKey) {
        await updateAgentConfig(name, { api_key: typedKey });
        setConfigApiKey("");
        setConfigKeyConfigured(true);
      }
      await refreshAgentDetection(name);
      const data = await fetchAgents();
      const agent = data.items.find((item) => item.name === name);
      const status = agent?.integration_status ?? "error";
      if (status === "ready") setConfigNotice("测试通过：ACP 握手正常，可提交任务。");
      else if (status === "auth_required") setConfigError(`测试未通过：${agent?.detail ?? "凭据不可用"}`);
      else setConfigError(`测试未通过：${agent?.detail || status}`);
      await loadAgents();
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "测试连接失败");
    } finally {
      setKeyTesting(false);
    }
  };

  const testWorkBuddy = async (): Promise<void> => {
    setKeyTesting(true);
    setConfigError("");
    setConfigNotice("");
    try {
      const typedKey = configApiKey.trim();
      if (typedKey) {
        await updateAgentConfig("workbuddy", { api_key: typedKey });
        setConfigApiKey("");
        setConfigKeyConfigured(true);
      }
      // session/new 不校验登录，握手必然「成功」；真实结论来自后台那条极短 session/prompt
      // 探针（约 4~20 秒落地）。所以这里刷新一次后轮询，直到探针结论替换掉握手结果。
      await refreshAgentDetection("workbuddy");
      let status = "ready";
      for (let i = 0; i < 10; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2500));
        const data = await fetchAgents();
        status = data.items.find((item) => item.name === "workbuddy")?.integration_status ?? "error";
        if (status !== "ready") break;
      }
      if (status === "ready") setConfigNotice("测试通过：凭据可用，能提交真实任务。");
      else if (status === "auth_required") setConfigError("测试未通过：凭据无效或额度不足，请核对 API Key。");
      else setConfigError(`测试未通过：${status}`);
      await loadAgents();
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "测试连接失败");
    } finally {
      setKeyTesting(false);
    }
  };

  const reload = async (): Promise<void> => {
    try {
      const nextTasks = await fetchTasks();
      setTasks(nextTasks);
      await reloadRuns(nextTasks);
      setTaskError("");
    } catch (e) {
      setTaskError(e instanceof Error ? e.message : "任务列表加载失败");
    }
  };

  const reloadRuns = async (sourceTasks: Task[] = tasks): Promise<void> => {
    try {
      const next: Record<string, AgentRun> = {};
      await Promise.all(
        sourceTasks.slice(0, 30).map(async (task) => {
          const run = await fetchTaskRun(task.task_id);
          if (run) next[task.task_id] = run;
        }),
      );
      setRuns(next);
    } catch (e) {
      setTaskError(e instanceof Error ? `运行状态获取失败：${e.message}` : "运行状态获取失败");
    }
  };

  const hasActiveRuns = (): boolean =>
    Object.values(runs).some((run) => ["queued", "running", "awaiting_approval"].includes(run.status));

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (hasActiveRuns()) void reloadRuns();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runs]);

  useEffect(() => {
    void reload();
  }, []);

  useEffect(() => {
    void loadAgents();
  }, []);

  useEffect(() => {
    if (!taskNotice) return;
    const timer = window.setTimeout(() => setTaskNotice(""), 2400);
    return () => window.clearTimeout(timer);
  }, [taskNotice]);

  const classify = async (): Promise<void> => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      const result = await routeTask(input);
      setRouting({ task: result.task, status: `已分流为 ${result.task.category}` });
      setInput("");
      await reload();
    } finally {
      setLoading(false);
    }
  };

  const applyTaskStatus = async (task: Task, status: TaskActionStatus): Promise<void> => {
    if (busyTask?.taskId === task.task_id) return;
    const action = TASK_ACTIONS.find((item) => item.status === status);
    setTaskNotice("");
    setTaskError("");
    setBusyTask({ taskId: task.task_id, status });
    try {
      await markTask(task.task_id, status);
      setTaskNotice(`已更新为「${action?.label ?? status}」`);
      await reload();
    } catch (e) {
      setTaskError(e instanceof Error ? `任务状态更新失败：${e.message}` : "任务状态更新失败");
    } finally {
      setBusyTask(null);
    }
  };

  // 忙时不静默吞点击：按钮 disabled 只管住当前动作，别的动作进行中仍会落到这里。
  const busyHint = (): void => setTaskNotice("有执行操作正在进行，请等它结束再试。");

  const startRun = async (task: Task, executor: string | null): Promise<void> => {
    if (busyRun) {
      busyHint();
      return;
    }
    const mode = runModes[task.task_id] ?? "read-only";
    setTaskNotice("");
    setTaskError("");
    setBusyRun("run");
    try {
      const result = await executeTask(task.task_id, { executor, mode });
      setTaskNotice(`已交给 ${result.run.executor}（${mode}）`);
      setRunModes((prev) => ({ ...prev, [task.task_id]: mode }));
      setRuns((prev) => ({ ...prev, [task.task_id]: result.run }));
      await reload();
    } catch (e) {
      setTaskError(e instanceof Error ? `运行失败：${e.message}` : "运行失败");
    } finally {
      setBusyRun("");
    }
  };

  const stopRun = async (task: Task): Promise<void> => {
    const run = runs[task.task_id];
    if (!run) return;
    if (busyRun) {
      busyHint();
      return;
    }
    setTaskNotice("");
    setTaskError("");
    setBusyRun("cancel");
    try {
      const updated = await cancelRun(run.run_id);
      setRuns((prev) => ({ ...prev, [task.task_id]: updated }));
      setTaskNotice("已取消执行");
      await reload();
    } catch (e) {
      setTaskError(e instanceof Error ? `取消失败：${e.message}` : "取消失败");
    } finally {
      setBusyRun("");
    }
  };

  const decideAction = async (task: Task, decision: "approved" | "rejected"): Promise<void> => {
    const run = runs[task.task_id];
    if (!run) return;
    if (busyRun) {
      busyHint();
      return;
    }
    setTaskNotice("");
    setTaskError("");
    setBusyRun(decision);
    try {
      const updated = await decideRun(run.run_id, decision);
      setRuns((prev) => ({ ...prev, [task.task_id]: updated }));
      setTaskNotice(decision === "approved" ? "已批准当前操作" : "已拒绝当前操作");
      await reload();
    } catch (e) {
      setTaskError(e instanceof Error ? `授权操作失败：${e.message}` : "授权操作失败");
    } finally {
      setBusyRun("");
    }
  };

  const agentByName = (name: string | null): AgentInfo | undefined =>
    agentItems.find((item) => item.name === name);

  const resolveRun = (task: Task): { executor: string | null; ready: boolean; detail: string; run?: AgentRun } => {
    const run = runs[task.task_id];
    const executorName = task.preferred_executor || defaultExecutor || "codex";
    const agent = agentByName(executorName);
    const ready = Boolean(agent?.available && agent.integration_status === "ready");
    return { executor: agent?.name || executorName, ready, detail: agent?.detail ?? "", run };
  };

  const canStartRun = (task: Task): boolean => {
    if (!["delegate_backend", "request_approval"].includes(task.category)) return false;
    if (["running", "completed", "cancelled"].includes(task.status)) return false;
    const current = runs[task.task_id];
    return !current || !["queued", "running", "awaiting_approval"].includes(current.status);
  };

  return (
    <section className="flex flex-col gap-3.5">
      {/* Task routing card */}
      <section className="rounded-lg border border-line bg-surface shadow-card p-4">
        <div className="flex items-center justify-between gap-2.5 mb-3">
          <h3 className="text-sm font-semibold text-ink">任务路由</h3>
          <button className="text-brand text-xs hover:underline" onClick={() => void reload()}>刷新</button>
        </div>
        <div className="flex gap-2 items-center">
          <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入一句话试着分流" />
          <button className="h-[38px] px-3.5 rounded-lg bg-brand text-onbrand text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50" onClick={() => void classify()} disabled={loading}>{loading ? "分流中…" : "分流"}</button>
        </div>
        {routing.task && (
          <div className="mt-3 rounded-lg border border-ok/30 bg-ok-50 px-3 py-2.5 text-xs text-ok">
            最新路由：{routing.task.category} / {routing.task.risk_level} / {routing.task.status}
          </div>
        )}
      </section>

      {/* Executor status card */}
      <section className="rounded-lg border border-line bg-surface shadow-card p-4 min-w-0">
        <div className="flex items-center justify-between gap-2.5 mb-3">
          <h3 className="text-sm font-semibold text-ink">执行器状态</h3>
          <button className="text-brand text-xs hover:underline" onClick={() => void loadAgents()} disabled={agentLoading}>
            {agentLoading ? "刷新中" : "刷新"}
          </button>
        </div>
        {defaultExecutor && <p className="text-xs text-muted mb-1.5 break-anywhere">默认执行器：<code className="font-mono">{defaultExecutor}</code></p>}
        {flagNotice && <p className="text-xs text-ok mb-1.5 break-anywhere">{flagNotice}</p>}
        {flagError && <p className="text-xs text-bad mb-1.5 break-anywhere">{flagError}</p>}
        {agentError && <div className="rounded-lg bg-bad-50 text-bad px-3.5 py-2.5 text-sm mb-2">{agentError}</div>}
        {agentLoading && agentItems.length === 0 ? (
          <p className="text-sm text-muted">正在探测执行器…</p>
        ) : agentItems.length === 0 && !agentError ? (
          <div className="border border-dashed border-line rounded-lg px-4 py-6 text-center">
            <p className="text-sm text-muted">未返回执行器信息</p>
            <p className="text-xs text-muted mt-1">确认 ai-service 已启动后点「刷新」重新探测。</p>
          </div>
        ) : agentItems.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-2.5">
            {agentItems.map((agent) => {
              const st = agent.integration_status;
              const isDefault = agent.name === defaultExecutor;
              const pill = agent.enabled ? AGENT_PILL[st] : AGENT_DISABLED_PILL;
              return (
                <div key={agent.name} className={`min-w-0 border rounded-lg p-3 ${AGENT_CARD_CLS[st]}`}>
                  <div className="flex items-start justify-between gap-2.5">
                    <div className="min-w-0">
                      <b className="block text-sm leading-tight break-anywhere">{agent.label}</b>
                      <span className="block mt-0.5 text-[11px] text-muted font-mono break-all">{agent.name}</span>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${pill.pill}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${pill.dot}`} />
                      {agent.enabled ? AGENT_STATUS_ZH[st] : "已停用"}
                    </span>
                  </div>
                  <p className={`text-[11px] leading-relaxed mt-1.5 ${pill.noteCls}`}>{pill.note}</p>
                  <ul className="list-none flex flex-wrap gap-x-3 gap-y-1 mt-2 text-xs">
                    <li><span className="text-muted">available</span> <b className={agent.available ? "text-ok" : "text-bad"}>{agent.available ? "是" : "否"}</b></li>
                    <li><span className="text-muted">版本</span> <b>{agent.version ?? "—"}</b></li>
                    <li><span className="text-muted">协议</span> <b>{agent.protocol ?? "—"}</b></li>
                  </ul>
                  <div className="mt-2 flex items-center justify-between gap-2 border-t border-line pt-2">
                    <label
                      className="flex items-center gap-1.5 text-[11px] text-muted shrink-0"
                      title={isDefault ? "当前默认执行器：先切换默认再停用" : "停用后该执行器不参与任务执行"}
                    >
                      <input
                        type="checkbox"
                        className="w-3.5 h-3.5 accent-brand"
                        checked={agent.enabled}
                        disabled={Boolean(flagBusy) || (isDefault && agent.enabled)}
                        onChange={(e) => void setExecutorFlag(
                          agent.name,
                          { enabled: e.target.checked },
                          `${agent.label} ${e.target.checked ? "已启用" : "已停用"}。`,
                        )}
                      />
                      启用
                    </label>
                    {isDefault ? (
                      <span className="shrink-0 rounded-full bg-brand-100 text-brand px-2 py-0.5 text-[11px] font-medium">默认执行器</span>
                    ) : agent.default_eligible && agent.enabled ? (
                      <button
                        className="px-2.5 py-1 rounded-md border border-line text-xs text-ink hover:bg-surface-secondary transition-colors disabled:opacity-50 shrink-0"
                        disabled={Boolean(flagBusy) || !agent.available}
                        onClick={() => void setExecutorFlag(agent.name, { set_default: true }, `默认执行器已切换为 ${agent.label}。`)}
                      >
                        {flagBusy === agent.name ? "保存中…" : "设为默认"}
                      </button>
                    ) : null}
                  </div>
                  {agent.detail && <p className="text-xs text-muted mt-2 leading-relaxed break-anywhere">{agent.detail}</p>}
                  {(["codex", "workbuddy", "acp-cli"].includes(agent.adapter)) && (
                    configName === agent.name ? (
                      <div className="mt-2.5 border-t border-line pt-2.5 flex flex-col gap-2 min-w-0">
                        <div>
                          <p className="text-[11px] text-muted mb-1">{agent.label} 可执行文件路径</p>
                          <input
                            className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                            value={configCommand}
                            onChange={(e) => setConfigCommand(e.target.value)}
                            placeholder="留空 = 自动检测"
                          />
                          <p className="text-[11px] text-muted mt-1">留空保存即恢复自动检测。</p>
                        </div>
                        {(agent.name === "workbuddy" || configKeyEnv) && (
                          <div className="border-t border-line pt-2.5">
                            <p className="text-[11px] text-muted mb-1">API Key（自备凭据）</p>
                            <input
                              className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                              type="password"
                              autoComplete="off"
                              value={configApiKey}
                              onChange={(e) => setConfigApiKey(e.target.value)}
                              placeholder={configKeyConfigured ? "已配置（留空则不改动）" : "粘贴 API Key"}
                            />
                            <p className="text-[11px] text-muted mt-1 leading-relaxed">
                              {configLoginHint ? (
                                <>
                                  {configLoginHint}
                                  {configSignupUrl && (
                                    <>
                                      {" "}到{" "}
                                      <a
                                        href={configSignupUrl}
                                        target="_blank"
                                        rel="noreferrer noopener"
                                        className="text-brand hover:underline"
                                      >
                                        {configSignupUrl.replace(/^https?:\/\//, "").split("/")[0]}
                                      </a>{" "}
                                      获取。
                                    </>
                                  )}
                                </>
                              ) : (
                                <>
                                  WorkBuddy 的 API Key 需先订阅付费版才能申请，是否订阅由你决定。
                                  到{" "}
                                  <a
                                    href="https://copilot.tencent.com/profile/"
                                    target="_blank"
                                    rel="noreferrer noopener"
                                    className="text-brand hover:underline"
                                  >
                                    copilot.tencent.com/profile
                                  </a>{" "}
                                  申请后粘贴到这里。桌面端登录态栖灵读不到，只能走自备 Key。
                                </>
                              )}
                            </p>
                            <div className="flex flex-wrap gap-2 mt-1.5">
                              <button
                                className="px-2.5 py-1 rounded-md border border-line text-xs text-ink hover:bg-surface-secondary transition-colors disabled:opacity-50"
                                onClick={() => void (agent.name === "workbuddy" ? testWorkBuddy() : testAgentConnection(agent.name))}
                                disabled={keyTesting || configSaving || (!configApiKey.trim() && !configKeyConfigured)}
                              >
                                {keyTesting ? "测试中…" : "测试连接"}
                              </button>
                              {configKeyConfigured && (
                                <button
                                  className="px-2.5 py-1 rounded-md text-xs text-muted hover:text-bad transition-colors disabled:opacity-50"
                                  onClick={() => void clearAgentKey(agent.name)}
                                  disabled={keyTesting || configSaving}
                                >
                                  清除 Key
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                        {configNotice && <p className="text-[11px] text-ok">{configNotice}</p>}
                        {configError && <p className="text-[11px] text-bad break-anywhere">{configError}</p>}
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="px-2.5 py-1 rounded-md bg-brand text-onbrand text-xs font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                            onClick={() => void saveAgentConfig(agent.name)}
                            disabled={configSaving}
                          >
                            {configSaving ? "保存中…" : "保存"}
                          </button>
                          <button
                            className="px-2.5 py-1 rounded-md border border-line text-xs text-ink hover:bg-surface-secondary transition-colors disabled:opacity-50"
                            onClick={() => void saveAgentConfig(agent.name, null)}
                            disabled={configSaving}
                          >
                            恢复自动
                          </button>
                          <button
                            className="px-2.5 py-1 rounded-md text-xs text-muted hover:text-ink transition-colors disabled:opacity-50"
                            onClick={closeAgentConfig}
                            disabled={configSaving}
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-2.5 border-t border-line pt-2 flex items-center justify-between gap-2">
                        <span className="text-[11px] text-muted font-mono truncate min-w-0">
                          {agent.command ? `路径 ${agent.command}` : "未检测到可执行文件"}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {!agent.enabled && (
                            <button
                              className="px-2.5 py-1 rounded-md bg-brand text-onbrand text-xs font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                              disabled={Boolean(flagBusy)}
                              onClick={() => void setExecutorFlag(
                                agent.name,
                                { enabled: true },
                                `${agent.label} 已添加并启用。`,
                              )}
                            >
                              添加
                            </button>
                          )}
                          <button
                            className="px-2.5 py-1 rounded-md border border-line text-xs text-ink hover:bg-surface-secondary transition-colors shrink-0"
                            onClick={() => void openAgentConfig(agent.name)}
                          >
                            配置
                          </button>
                        </div>
                      </div>
                    )
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
        {agentItems.length > 0 && (
          <div className="mt-3 border-t border-line pt-3">
            {customOpen ? (
              <div className="flex flex-col gap-2">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <div>
                    <p className="text-[11px] text-muted mb-1">名称</p>
                    <input
                      className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      placeholder="my-agent"
                    />
                  </div>
                  <div>
                    <p className="text-[11px] text-muted mb-1">启动命令</p>
                    <input
                      className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                      value={customCommand}
                      onChange={(e) => setCustomCommand(e.target.value)}
                      placeholder="my-agent --acp"
                    />
                  </div>
                  <div>
                    <p className="text-[11px] text-muted mb-1">凭据环境变量名（可选）</p>
                    <input
                      className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                      value={customKeyEnv}
                      onChange={(e) => setCustomKeyEnv(e.target.value)}
                      placeholder="MY_AGENT_API_KEY"
                    />
                  </div>
                  <div>
                    <p className="text-[11px] text-muted mb-1">API Key（可选）</p>
                    <input
                      className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-surface focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                      type="password"
                      autoComplete="off"
                      value={customKey}
                      onChange={(e) => setCustomKey(e.target.value)}
                      placeholder="留空则用该 CLI 自身登录态"
                    />
                  </div>
                </div>
                {customError && <p className="text-[11px] text-bad break-anywhere">{customError}</p>}
                <div className="flex flex-wrap gap-2">
                  <button
                    className="px-2.5 py-1 rounded-md bg-brand text-onbrand text-xs font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                    onClick={() => void submitCustomAgent()}
                    disabled={customBusy || !customName.trim() || !customCommand.trim()}
                  >
                    {customBusy ? "添加中…" : "添加"}
                  </button>
                  <button
                    className="px-2.5 py-1 rounded-md text-xs text-muted hover:text-ink transition-colors disabled:opacity-50"
                    onClick={() => { setCustomOpen(false); setCustomError(""); }}
                    disabled={customBusy}
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="text-brand text-xs hover:underline"
                onClick={() => setCustomOpen(true)}
              >
                添加自定义执行器
              </button>
            )}
          </div>
        )}
      </section>

      {/* Recent tasks card */}
      <section className="rounded-lg border border-line bg-surface shadow-card p-4">
        <div className="flex items-center justify-between gap-2.5 mb-3">
          <h3 className="text-sm font-semibold text-ink">最近任务</h3>
          <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted">本地任务台</span>
        </div>
        {taskNotice && <div className="rounded-lg border border-ok/30 bg-ok-50 px-3 py-2.5 text-xs text-ok mb-2">{taskNotice}</div>}
        {taskError && <div className="rounded-lg bg-bad-50 text-bad px-3.5 py-2.5 text-sm mb-2">{taskError}</div>}
        <div className="flex flex-col gap-2 max-h-[560px] overflow-auto">
          {tasks.length === 0 && (
            <div className="border border-dashed border-line rounded-lg px-4 py-6 text-center">
              <p className="text-sm text-muted">暂无任务</p>
              <p className="text-xs text-muted mt-1">在上方「任务路由」输入一句话完成分流后，任务会出现在这里。</p>
            </div>
          )}
          {tasks.map((task) => {
            const resolved = resolveRun(task);
            const run = resolved.run;
            const runBusy = busyRun === "run";
            const runActive = Boolean(run && ["queued", "running", "awaiting_approval"].includes(run.status));
            return (
              <div key={task.task_id} className="border border-line rounded-lg p-3 flex flex-col gap-1.5 min-w-0">
                <b className="text-[13px] text-ink break-anywhere">{task.input}</b>
                <span className="text-[11px] text-muted break-anywhere">{task.category} · {task.risk_level} · {task.status} · {task.preferred_executor ?? "—"}</span>
                {!agentLoading && agentItems.length > 0 && !resolved.ready && canStartRun(task) && (
                  <div className="rounded-lg bg-warn-50 text-warn px-3.5 py-2.5 text-xs leading-relaxed break-anywhere" role="status" title={resolved.detail || undefined}>
                    执行器「{resolved.executor || defaultExecutor || "codex"}」当前不可用；已保留任务，修复配置后可刷新运行。
                  </div>
                )}
                {run && (
                  <div className="flex items-center flex-wrap gap-1.5">
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${RUN_STATUS_PILL[run.status]}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${RUN_STATUS_DOT[run.status]}`} />
                      {RUN_STATUS_ZH[run.status]}
                    </span>
                    <span className="text-xs text-muted break-anywhere">{run.executor} · {run.mode}</span>
                    {runActive && run.progress && (
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-brand break-anywhere">
                        <span className="w-1 h-1 rounded-full bg-brand animate-breathe" />
                        {run.progress}
                      </span>
                    )}
                    {!runActive && run.progress && <span className="text-xs text-muted break-anywhere">{run.progress}</span>}
                    {run.error && <span className="basis-full text-xs text-bad mt-0.5 break-anywhere" title={run.error}>{run.error}</span>}
                    {run.result && !run.error && !runActive && (
                      <span className="basis-full text-xs text-ink mt-0.5 break-anywhere" title={run.result}>{run.result}</span>
                    )}
                  </div>
                )}
                {resolved.ready && canStartRun(task) && (
                  <div className="grid grid-cols-[minmax(0,180px)_minmax(0,120px)] gap-1.5 mt-1">
                    <select
                      className="min-w-0 min-h-[30px] border border-line rounded-lg px-2 text-xs focus:outline-none focus:border-brand"
                      value={runModes[task.task_id] ?? "read-only"}
                      onChange={(e) =>
                        setRunModes((prev) => ({ ...prev, [task.task_id]: e.target.value as AgentRunMode }))
                      }
                      aria-label="执行模式"
                    >
                      <option value="read-only">只读</option>
                      <option value="agent">Agent</option>
                      <option value="agent-full-access">完整授权</option>
                    </select>
                    <button
                      className="min-h-[30px] rounded-lg bg-brand-100 border border-brand-200 text-brand text-xs font-medium hover:bg-brand-200 transition-colors disabled:opacity-50"
                      type="button"
                      disabled={busyRun === "run"}
                      onClick={() => void startRun(task, resolved.executor)}
                    >
                      {runBusy ? "提交中…" : task.status === "failed" ? "重试" : "运行"}
                    </button>
                  </div>
                )}
                {runActive && (
                  <div className="grid grid-cols-[repeat(auto-fit,minmax(96px,1fr))] gap-1.5 mt-1">
                    {run?.status === "awaiting_approval" && (
                      <>
                        <button
                          className="min-h-[30px] rounded-lg bg-ok-50 border border-ok-50 text-ok text-xs font-medium hover:opacity-80 transition-opacity disabled:opacity-50"
                          type="button"
                          disabled={Boolean(busyRun)}
                          onClick={() => void decideAction(task, "approved")}
                        >
                          批准
                        </button>
                        <button
                          className="min-h-[30px] rounded-lg bg-bad-50 border border-bad-50 text-bad text-xs font-medium hover:opacity-80 transition-opacity disabled:opacity-50"
                          type="button"
                          disabled={Boolean(busyRun)}
                          onClick={() => void decideAction(task, "rejected")}
                        >
                          拒绝
                        </button>
                      </>
                    )}
                    <button
                      className="min-h-[30px] rounded-lg bg-warn-50 border border-warn-50 text-warn text-xs font-medium hover:opacity-80 transition-opacity disabled:opacity-50"
                      type="button"
                      disabled={Boolean(busyRun)}
                      onClick={() => void stopRun(task)}
                    >
                      取消
                    </button>
                  </div>
                )}
                <div className="flex items-start gap-2 mt-1">
                  <span className="self-center text-[11px] text-muted whitespace-nowrap">手工调试</span>
                  <div className="grid grid-cols-4 gap-1.5 flex-1 min-w-0">
                  {TASK_ACTIONS.map((option) => {
                    const isCurrent = task.status === option.status;
                    const isBusy = busyTask?.taskId === task.task_id;
                    const isBusyAction = isBusy && busyTask?.status === option.status;
                    return (
                      <button
                        key={option.status}
                        className={`min-h-[30px] rounded-lg border text-xs font-medium transition-colors ${
                          isCurrent
                            ? "bg-brand-100 border-brand-200 text-brand"
                            : isBusyAction
                              ? "bg-brand-50 border-brand text-brand"
                              : "bg-surface border-line text-ink hover:border-brand hover:text-brand"
                        } disabled:opacity-50`}
                        type="button"
                        disabled={isCurrent || isBusy}
                        onClick={() => void applyTaskStatus(task, option.status)}
                        aria-pressed={isCurrent}
                      >
                        {isBusyAction ? "更新中" : option.label}
                      </button>
                    );
                  })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </section>
  );
}

function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const loadSettings = async (): Promise<void> => {
    try {
      setSettings(await fetchSettings());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "设置加载失败");
    }
  };

  useEffect(() => {
    void loadSettings();
  }, []);

  if (!settings) {
    return (
      <section className="rounded-lg border border-line bg-surface shadow-card p-4">
        <h2 className="text-xl font-bold text-ink mb-3">设置</h2>
        <p className="text-sm text-muted">{error || "加载中…"}</p>
      </section>
    );
  }

  const save = async (body: Record<string, unknown>, label: string): Promise<void> => {
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const nextSettings = await updateSettings(body);
      setSettings(nextSettings);
      setNotice(label);
      // 语音等设置会被挂件窗口复用：广播一次让别处刷新自己的快照。
      if (isTauri()) void emit("settings-changed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const voiceCfg = settings.voice.dashscope_configured || settings.voice.minimax_configured;
  const liteMode = settings.performance_mode === "lite";

  const saveSystem = (): void => {
    const body: Record<string, unknown> = {
      ui_language: settings.ui.language,
      ui_theme: settings.ui.theme,
      permission_level: settings.permission_level,
      performance_mode: settings.performance_mode,
      voice_enabled: settings.voice.enabled,
      voice_auto_speak: settings.voice.auto_speak,
      activation_enabled: settings.voice.activation_enabled,
      activation_default_state: settings.voice.activation_default_state,
    };
    void save(body, "已保存。");
  };

  const inputCls = "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";
  const cardCls = "rounded-lg border border-line bg-surface shadow-card p-4 flex flex-col gap-3 min-w-0";

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted leading-relaxed">系统级配置集中在此；角色相关的形象、语音与唤醒请在「角色卡」页编辑。</p>
        <div className="flex items-center gap-3 shrink-0">
          {notice && <span className="text-sm text-ok">{notice}</span>}
          {error && <span className="text-sm text-bad">{error}</span>}
          <button
            className="px-4 py-2 text-sm font-medium rounded-lg bg-brand text-onbrand hover:bg-brand-600 transition-colors disabled:opacity-50"
            onClick={saveSystem}
            disabled={saving}
          >
            {saving ? "保存中…" : "保存系统设置"}
          </button>
        </div>
      </div>

      <ModelProfilesSection onChanged={loadSettings} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-start">
        {/* 权限 */}
        <section className={cardCls}>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="text-sm font-semibold text-ink">权限</h3>
            <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted">任务授权</span>
          </div>
          <label className="flex flex-col gap-1.5 text-xs text-muted">权限级别
            <select className={inputCls} value={settings.permission_level} onChange={(e) => setSettings({ ...settings, permission_level: e.target.value })}>
              <option value="confirm_risky">高风险操作确认</option>
              <option value="confirm_all">所有外部操作确认</option>
              <option value="read_only">只读模式</option>
            </select>
            <small className="text-[11px] text-muted">当前只影响配置记录，任务授权流将在后续 Step 接入。</small>
          </label>
        </section>

        {/* 语音能力总开关（全局） */}
        <section className={cardCls}>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="text-sm font-semibold text-ink">语音能力</h3>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${voiceCfg ? "bg-ok-50 text-ok" : "bg-warn-50 text-warn"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${voiceCfg ? "bg-ok" : "bg-warn"}`} />
              {voiceCfg ? "语音已配置" : "未配置语音"}
            </span>
          </div>
          <label className="flex flex-row items-center justify-between gap-3">
            <span className="text-xs text-muted">启用语音（总开关）</span>
            <input type="checkbox" className="w-4 h-4 accent-brand" checked={settings.voice.enabled} disabled={liteMode} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, enabled: e.target.checked } })} />
          </label>
          <label className="flex flex-row items-center justify-between gap-3">
            <span className="text-xs text-muted">自动播报回复</span>
            <input type="checkbox" className="w-4 h-4 accent-brand" checked={settings.voice.auto_speak} disabled={liteMode || !settings.voice.enabled} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, auto_speak: e.target.checked } })} />
          </label>
          <small className="text-[11px] text-muted -mt-1">关闭后语音输入仍可用，回复不自动朗读（任务待确认提醒的语音播报一并关闭）；消息下方播报按钮仍可手动播报。</small>
          <label className="flex flex-row items-center justify-between gap-3">
            <span className="text-xs text-muted">启用语音激活（唤醒与静默）</span>
            <input type="checkbox" className="w-4 h-4 accent-brand" checked={settings.voice.activation_enabled} disabled={liteMode || !settings.voice.enabled} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, activation_enabled: e.target.checked } })} />
          </label>
          <label className="flex flex-col gap-1.5 text-xs text-muted">默认状态
            <select className={inputCls} value={settings.voice.activation_default_state} disabled={liteMode || !settings.voice.enabled || !settings.voice.activation_enabled} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, activation_default_state: e.target.value } })}>
              <option value="listening">常开监听</option>
              <option value="sleeping">静默等待唤醒</option>
            </select>
            <small className="text-[11px] text-muted">全局默认状态；各角色卡的唤醒词、静默指令与语音特征在「角色卡」页绑定。</small>
          </label>
          {liteMode && (
            <div className="rounded-lg bg-warn-50 text-warn px-3 py-2.5 text-xs leading-relaxed">当前为轻量模式，语音已关闭；切回「均衡/高质量」后可重新开启。</div>
          )}
        </section>

        {/* 性能模式 */}
        <section className={cardCls}>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="text-sm font-semibold text-ink">性能模式</h3>
            <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted">运行策略</span>
          </div>
          <label className="flex flex-col gap-1.5 text-xs text-muted">模式
            <select className={inputCls} value={settings.performance_mode ?? "balanced"} onChange={(e) => setSettings({ ...settings, performance_mode: e.target.value as AppSettings["performance_mode"] })}>
              <option value="quality">高质量（全功能）</option>
              <option value="balanced">均衡（默认）</option>
              <option value="lite">轻量（仅文字，关闭语音）</option>
            </select>
            <small className="text-[11px] text-muted">轻量模式关闭语音与动画，适合低内存或无 GPU 设备。</small>
          </label>
        </section>

        {/* 外观 */}
        <section className={cardCls}>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="text-sm font-semibold text-ink">外观</h3>
            <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted">界面</span>
          </div>
          <label className="flex flex-col gap-1.5 text-xs text-muted">界面主题
            <select className={inputCls} value={settings.ui.theme} onChange={(e) => { applyTheme(e.target.value); setSettings({ ...settings, ui: { ...settings.ui, theme: e.target.value } }); }}>
              <option value="system">跟随系统</option>
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
            <small className="text-[11px] text-muted">「跟随系统」会随 macOS / Windows 的浅色·深色外观自动切换。</small>
          </label>
        </section>

        {/* 系统维护 */}
        <section className={cardCls}>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="text-sm font-semibold text-ink">系统维护</h3>
            <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted">后续填充</span>
          </div>
          <div className="text-xs text-muted py-3 text-center leading-relaxed">本地数据备份、运行日志清理、更新检查等维护项将在后续版本补充。</div>
        </section>
      </div>
    </div>
  );
}

function SetupWizard({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [dashscopeKey, setDashscopeKey] = useState("");
  const [minimaxKey, setMinimaxKey] = useState("");
  const [personas, setPersonas] = useState<PersonaCard[]>([]);
  const [personaId, setPersonaId] = useState("");
  const [personaError, setPersonaError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  // 进入角色步时拉一次角色清单；失败不阻断向导（默认角色仍可用）。
  useEffect(() => {
    if (step !== 1 || personas.length > 0) return;
    fetchPersonas()
      .then((items) => {
        setPersonas(items);
        setPersonaId((cur) => cur || items[0]?.id || "default");
      })
      .catch(() => setPersonaError(true));
  }, [step, personas.length]);

  const finish = async (withVoice: boolean): Promise<void> => {
    setSaving(true);
    setErr("");
    try {
      const body: Record<string, unknown> = {
        llm_base_url: baseUrl.trim(),
        llm_api_key: apiKey.trim(),
        llm_model: model.trim(),
        setup_completed: true,
      };
      // 选了非默认角色才写，避免对未改动用户多一次角色切换。
      if (personaId && personaId !== "default") body.active_persona_id = personaId;
      if (withVoice) {
        if (dashscopeKey.trim()) body.dashscope_api_key = dashscopeKey.trim();
        if (minimaxKey.trim()) body.minimax_api_key = minimaxKey.trim();
      }
      await updateSettings(body);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-full px-3 py-2 text-sm rounded-lg border border-line bg-surface text-ink focus:outline-none focus:border-brand";
  const stepTitle = ["配置对话模型", "选择角色", "配置语音（可跳过）"][step] ?? "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-surface shadow-card overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-line">
          <h2 className="text-lg font-bold text-ink">欢迎使用栖灵</h2>
          <p className="text-xs text-muted mt-1">第 {step + 1} 步 / 共 3 步 · {stepTitle}</p>
        </div>

        <div className="px-6 py-5 space-y-4">
          {step === 0 ? (
            <>
              <div>
                <label className="block text-xs font-medium text-ink mb-1.5">API Base URL</label>
                <input className={inputCls} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://api.openai.com/v1" />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink mb-1.5">API Key</label>
                <input className={inputCls} type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..." />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink mb-1.5">模型名称</label>
                <input className={inputCls} value={model} onChange={(e) => setModel(e.target.value)}
                  placeholder="gpt-4o-mini" />
              </div>
            </>
          ) : step === 1 ? (
            <>
              <p className="text-xs text-muted leading-relaxed">
                选择一个默认角色，决定栖灵的性格与呈现风格；之后可在「角色卡」页随时切换或新建。
              </p>
              {personaError ? (
                <p className="text-xs text-warn">角色清单加载失败，将保留默认角色，可稍后在角色卡页修改。</p>
              ) : personas.length === 0 ? (
                <p className="text-xs text-muted">加载中…</p>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                  {personas.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPersonaId(p.id)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors cursor-pointer ${
                        personaId === p.id ? "border-brand bg-brand-50" : "border-line hover:bg-surface-secondary"
                      }`}
                    >
                      {p.avatar?.trim() ? (
                        <img src={p.avatar} alt="" className="w-9 h-9 rounded-full object-cover shrink-0" />
                      ) : (
                        <span className="w-9 h-9 rounded-full bg-surface-secondary shrink-0" />
                      )}
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-ink truncate">{p.name}</span>
                        <span className="block text-xs text-muted truncate">{p.description || p.kind || p.id}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <p className="text-xs text-muted leading-relaxed">
                语音为可选能力，用于语音输入和播报。现在不填也可以，之后在设置页随时配置。
              </p>
              <div>
                <label className="block text-xs font-medium text-ink mb-1.5">DashScope API Key（语音识别）</label>
                <input className={inputCls} type="password" value={dashscopeKey} onChange={(e) => setDashscopeKey(e.target.value)}
                  placeholder="可留空" />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink mb-1.5">MiniMax API Key（语音合成）</label>
                <input className={inputCls} type="password" value={minimaxKey} onChange={(e) => setMinimaxKey(e.target.value)}
                  placeholder="可留空" />
              </div>
            </>
          )}

          {err && <p className="text-xs text-bad">{err}</p>}
        </div>

        <div className="px-6 py-4 border-t border-line flex items-center justify-between gap-3">
          {step === 0 ? (
            <>
              <button type="button" className="text-xs text-muted hover:text-ink" onClick={() => finish(false)} disabled={saving}>
                跳过全部，稍后配置
              </button>
              <button type="button"
                className="px-4 py-2 text-sm font-medium rounded-lg bg-brand text-onbrand hover:bg-brand/90 disabled:opacity-50"
                disabled={saving || !baseUrl.trim() || !apiKey.trim()}
                onClick={() => setStep(1)}>
                下一步
              </button>
            </>
          ) : step === 1 ? (
            <>
              <button type="button" className="text-xs text-muted hover:text-ink" onClick={() => setStep(0)} disabled={saving}>
                上一步
              </button>
              <button type="button"
                className="px-4 py-2 text-sm font-medium rounded-lg bg-brand text-onbrand hover:bg-brand/90 disabled:opacity-50"
                disabled={saving}
                onClick={() => setStep(2)}>
                下一步
              </button>
            </>
          ) : (
            <>
              <button type="button" className="text-xs text-muted hover:text-ink" onClick={() => setStep(1)} disabled={saving}>
                上一步
              </button>
              <div className="flex gap-2">
                <button type="button" className="px-4 py-2 text-sm font-medium rounded-lg border border-line text-ink hover:bg-surface-secondary disabled:opacity-50"
                  disabled={saving} onClick={() => finish(false)}>
                  跳过语音
                </button>
                <button type="button"
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-brand text-onbrand hover:bg-brand/90 disabled:opacity-50"
                  disabled={saving} onClick={() => finish(true)}>
                  {saving ? "保存中…" : "完成"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 把设置里的界面主题落到 <html data-theme>；system 跟随系统偏好。 */
function applyTheme(mode: string): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = mode === "dark" || (mode !== "light" && prefersDark);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export default function App() {
  const [page, setPage] = useHashPage();
  const { t, i18n } = useTranslation();
  const toggleLanguage = useCallback(() => {
    i18n.changeLanguage(i18n.language === "en" ? "zh" : "en");
  }, [i18n]);

  // 语言以后端 AppSettings.ui.language 为准：首次加载同步一次，切换时回写。
  useEffect(() => {
    let alive = true;
    fetchSettings()
      .then((s) => {
        if (!alive) return;
        const lang = s.ui.language.startsWith("en") ? "en" : "zh";
        if (i18n.language !== lang) void i18n.changeLanguage(lang);
      })
      .catch(() => {});
    const applyLanguage = (lng: string) => {
      void updateSettings({ ui_language: lng === "en" ? "en-US" : "zh-CN" }).catch(() => {});
    };
    i18n.on("languageChanged", applyLanguage);
    return () => {
      alive = false;
      i18n.off("languageChanged", applyLanguage);
    };
  }, [i18n]);

  // 界面主题：设置项落到 <html data-theme>；system 跟随系统偏好并实时响应切换
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const modeRef = { current: "system" };
    const apply = (): void => applyTheme(modeRef.current);
    apply();
    const onChange = (): void => {
      if (modeRef.current === "system") apply();
    };
    mq.addEventListener("change", onChange);
    void fetchSettings()
      .then((next) => {
        modeRef.current = next.ui.theme;
        apply();
      })
      .catch(() => {});
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [voiceLeaseOwned, setVoiceLeaseOwned] = useState(false);
  // 主界面被隐藏（关闭按钮走 hide）时让出语音租约，挂件自动接管「听」。
  // 只有真隐藏/真显示会翻这个值：最小化、失焦、被遮挡都不算，语音留在主界面。
  const [mainUiVisible, setMainUiVisible] = useState(() => !isTauri());
  const [pendingConversation, setPendingConversation] = useState<
    { id: string; seq: number } | null
  >(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [widgetState, setWidgetState] = useState<WidgetStatusReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [serviceLost, setServiceLost] = useState(false);
  // 已关闭的降级提醒，按诊断名记忆（仅本会话）；error 项不可关闭。
  const [dismissedDiag, setDismissedDiag] = useState<Record<string, boolean>>({});
  const [retryTick, setRetryTick] = useState(0);
  const [demoMsg, setDemoMsg] = useState("");
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const setupLoadedRef = useRef(false);
  const stopRef = useRef<(() => void) | undefined>(undefined);
  // 曾经连上过服务：只有这种情况下的失联才算「栖灵退出了」
  const everOnlineRef = useRef(false);
  // 连续探活失败次数：单次超时/瞬时拒绝不算退出，避免误报
  const failStreakRef = useRef(0);

  const onEvent = useCallback((env: EventEnvelope) => {
    setEvents((prev) => [...prev.slice(-14), env]);
    const next = eventToState(env.event_type);
    if (next) {
      const now = new Date().toISOString();
      const payloadMsg =
        typeof env.payload?.message === "string" ? env.payload.message : null;
      setWidgetState({
        state: next,
        task_id: env.task_id,
        message:
          payloadMsg ??
          (next === "completed" && env.event_type === "task.failed"
            ? "任务失败"
            : null),
        timestamp: env.timestamp ?? now,
      });
      if (next === "interrupted") {
        // 瞬态：展示打断后回落到当前服务端状态
        window.setTimeout(async () => {
          const s = await fetchWidgetState();
          setWidgetState(s);
        }, 1400);
      }
    }
  }, []);

  // Fetch agents status
  useEffect(() => {
    let alive = true;
    const loadAgents = async () => {
      try {
        const data = await fetchAgents();
        if (alive) setAgents(data.items);
      } catch (e) {
        console.error('Failed to fetch agents:', e);
      }
    };
    void loadAgents();
    const timer = setInterval(loadAgents, 10000); // Refresh every 10s
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!isTauri()) return; // 浏览器直开 5173 时恒为可见，行为不变
    let disposed = false;
    let unlisten: (() => void) | undefined;
    const syncVisible = async (): Promise<void> => {
      // 问自己，别问挂件那套跨窗口命令：主界面是远程页面（127.0.0.1:8736），
      // 自定义命令一旦被 IPC 拒绝，旧实现把「调用失败」当成「窗口已隐藏」，
      // 租约一放开就永久留在挂件手里，对话窗口再也拿不回「听」。
      try {
        const visible = await getCurrentWindow().isVisible();
        if (!disposed) setMainUiVisible(visible);
      } catch {
        /* 状态未知就保持上一次判断，未知 != 隐藏 */
      }
    };
    void syncVisible();
    const pollTimer = window.setInterval(() => void syncVisible(), 2000);
    void listen<boolean>("main-ui-visibility", (event) => {
      setMainUiVisible(event.payload);
      window.setTimeout(() => void syncVisible(), 300);
    }).then((stop) => {
      if (disposed) stop();
      else unlisten = stop;
    });
    let unlistenConversation: (() => void) | undefined;
    void listen<string>("main-ui-open-conversation", (event) => {
      if (!event.payload) return;
      // 带一个自增序号：同一会话再次打开也要触发刷新，不能因值相同被跳过。
      setPendingConversation((prev) => ({ id: event.payload, seq: (prev?.seq ?? 0) + 1 }));
      setPage("chat");
    }).then((stop) => {
      if (disposed) stop();
      else unlistenConversation = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
      unlistenConversation?.();
      window.clearInterval(pollTimer);
    };
  }, []);

  useEffect(() => {
    if (page !== "chat" || !mainUiVisible) {
      setVoiceLeaseOwned(false);
      return;
    }

    let alive = true;
    let heartbeatTimer: number | undefined;
    let retryTimer: number | undefined;

    const acquire = async (): Promise<void> => {
      const acquired = await acquireVoiceLease(true);
      if (!alive) return;
      setVoiceLeaseOwned(acquired);
      if (!acquired) {
        retryTimer = window.setTimeout(() => void acquire(), 1000);
        return;
      }
      heartbeatTimer = window.setInterval(async () => {
        const renewed = await heartbeatVoiceLease();
        if (!alive || renewed) return;
        setVoiceLeaseOwned(false);
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = undefined;
        retryTimer = window.setTimeout(() => void acquire(), 1000);
      }, 6000);
    };

    const release = (): void => {
      void releaseVoiceLease();
    };

    void acquire();
    window.addEventListener("pagehide", release);
    return () => {
      alive = false;
      window.clearInterval(heartbeatTimer);
      window.clearTimeout(retryTimer);
      window.removeEventListener("pagehide", release);
      release();
    };
  }, [page, mainUiVisible]);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      // 只看 health/session 是否拿到；后面的挂件状态与事件流失败不算「服务没了」
      let online = false;
      try {
        const [h, s] = await Promise.all([fetchHealth(), fetchSession()]);
        if (!alive) return;
        online = true;
        setHealth(h);
        setSession(s);
        setError(null);
        // 首次启动引导状态：只在尚未加载时取一次，避免每 8s 覆盖向导内的本地状态
        if (setupLoadedRef.current === false) {
          try {
            const st = await fetchSetupStatus();
            if (alive) {
              setupLoadedRef.current = true;
              setSetupStatus(st);
            }
          } catch {
            /* 引导状态取不到不阻塞主界面 */
          }
        }
        const ws = await fetchWidgetState();
        if (alive && ws) setWidgetState(ws);
        if (!stopRef.current) {
          stopRef.current = connectEvents(s.ws_url, onEvent, setWsOpen);
        }
      } catch (e) {
        if (!alive) return;
        // 只有服务本身不可达才占用顶部错误横幅；挂件状态/事件流失败不算失联
        if (!online) {
          setError(e instanceof Error ? e.message : "无法连接本地服务");
        } else {
          console.warn("挂件状态或事件流刷新失败：", e);
        }
        setWsOpen(false);
      } finally {
        if (alive) {
          if (online) {
            everOnlineRef.current = true;
            failStreakRef.current = 0;
          } else {
            failStreakRef.current += 1;
          }
          setServiceLost(failStreakRef.current >= 2 && everOnlineRef.current);
        }
      }
    };
    void refresh();
    const timer = setInterval(refresh, 8000);
    return () => {
      alive = false;
      clearInterval(timer);
      stopRef.current?.();
      stopRef.current = undefined;
    };
  }, [onEvent, retryTick]);

  // serviceOk 表示「本地服务可达」：degraded（语音/执行器不可用）时应用主体仍可用。
  const serviceOk = !serviceLost && !!health;
  const diagErrors = (health?.diagnostics ?? []).filter((d) => d.status === "error");
  // 无 fix_action 的 degraded（如「暂无记忆条目」）是正常初始状态，不打扰用户。
  const diagWarnings = (health?.diagnostics ?? []).filter(
    (d) => d.status === "degraded" && !!d.fix_action,
  );
  const current = widgetState?.state ?? "idle";

  const runDemo = async (action: (typeof DEMO_ACTIONS)[number]) => {
    try {
      setDemoMsg("");
      await publishEvent({
        event_type: action.eventType,
        source: action.source,
        task_id: action.taskId,
        payload: { message: action.label },
      });
    } catch (e) {
      setDemoMsg(e instanceof Error ? e.message : "发布失败");
    }
  };

  const runSequence = async () => {
    const seq = ["speech.started", "conversation.input", "conversation.response"];
    const taskSeq = ["task.started", "task.approval_required", "task.completed"];
    for (const type of [...seq, ...taskSeq]) {
      const action = DEMO_ACTIONS.find((a) => a.eventType === type);
      if (!action) continue;
      await runDemo(action);
      await new Promise((r) => setTimeout(r, 1200));
    }
    setDemoMsg("演示完成：聆听 → 思考 → 说话 → 执行 → 授权 → 完成");
  };

  const showWizard = !!setupStatus && !setupStatus.completed && serviceOk;

  return (
    <div className="flex flex-col md:flex-row min-h-screen bg-surface-secondary">
      {showWizard && (
        <SetupWizard
          onDone={() => {
            setupLoadedRef.current = false;
            setSetupStatus({ completed: true, missing: [], llm_configured: true, voice_configured: setupStatus?.voice_configured ?? false });
          }}
        />
      )}
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-60 bg-surface border-r border-line px-4 py-6 shrink-0">
        <button
          type="button"
          className="flex items-center gap-2.5 px-2 mb-7 text-left cursor-pointer"
          onClick={() => setPage("home")}
        >
          <span className="relative flex items-center justify-center w-8 h-8">
            <QilingMark className="w-8 h-8" />
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-accent border-2 border-surface" />
          </span>
          <span className="flex flex-col leading-tight">
            <span className="text-[15px] font-semibold text-ink tracking-tightish">栖灵</span>
            <span className="text-[11px] text-muted">桌面工作伙伴</span>
          </span>
        </button>
        <nav className="flex flex-col gap-4">
          {NAV_GROUPS.map((group, gi) => (
            <div key={gi} className="flex flex-col gap-0.5">
              {group.items.map((key) => {
                const item = NAV.find((n) => n.key === key)!;
                const Icon = item.icon;
                const active = page === key;
                return (
                  <button
                    key={key}
                    className={`group relative flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] transition-all duration-200 ease-expo cursor-pointer ${
                      active
                        ? "bg-brand-50 text-brand font-semibold"
                        : "text-ink/80 hover:bg-surface-secondary hover:text-ink"
                    }`}
                    onClick={() => setPage(key)}
                  >
                    <span
                      className={`absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full bg-brand transition-all duration-200 ease-expo ${
                        active ? "h-5 opacity-100" : "h-0 opacity-0"
                      }`}
                    />
                    <Icon
                      size={16}
                      strokeWidth={active ? 2.2 : 1.8}
                      className={active ? "text-brand" : "text-muted group-hover:text-ink"}
                    />
                    <span>{t(`nav.${item.key}`)}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="mt-auto">
          <button
            type="button"
            onClick={toggleLanguage}
            className="mb-2 w-full flex items-center justify-center gap-1.5 rounded-md border border-line bg-surface px-3 py-2 text-[12px] font-medium text-ink/80 hover:bg-surface-secondary transition-colors cursor-pointer"
            aria-label="Switch language"
          >
            <Globe size={13} className="text-muted" />
            {i18n.language === "en" ? "中文" : "English"}
          </button>
          <div className="flex items-center gap-2 rounded-md bg-surface-secondary px-3 py-2.5">
            <span className="relative flex w-2 h-2">
              <span
                className={`absolute inline-flex w-full h-full rounded-full ${
                  serviceLost ? "bg-warn" : serviceOk ? "bg-ok" : "bg-bad"
                } ${serviceOk ? "animate-pulse-ring" : "opacity-80"}`}
              />
              <span
                className={`relative inline-flex w-2 h-2 rounded-full ${
                  serviceLost ? "bg-warn" : serviceOk ? "bg-ok" : "bg-bad"
                }`}
              />
            </span>
            <span className="text-[11px] text-muted">
              {serviceLost ? t("service.stopped") : serviceOk ? t("service.running") : t("service.offline")}
            </span>
          </div>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden flex items-center gap-2 px-4 py-3 bg-surface border-b border-line overflow-x-auto w-full shrink-0">
        <button
          type="button"
          className="flex items-center gap-1.5 mr-1 whitespace-nowrap cursor-pointer"
          onClick={() => setPage("home")}
        >
          <QilingMark className="w-6 h-6" />
          <b className="text-sm text-ink">栖灵</b>
        </button>
        <button
          type="button"
          onClick={toggleLanguage}
          className="ml-1 px-2.5 py-1.5 rounded-full border border-line text-xs text-ink/70 whitespace-nowrap cursor-pointer"
          aria-label="Switch language"
        >
          {i18n.language === "en" ? "中" : "EN"}
        </button>
        {NAV.map((item) => (
          <button
            key={item.key}
            className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors cursor-pointer ${
              page === item.key
                ? "bg-brand-50 text-brand font-semibold"
                : "text-ink/70 hover:bg-surface-secondary"
            }`}
            onClick={() => setPage(item.key)}
          >
            {t(`nav.${item.key}`)}
          </button>
        ))}
      </div>

      <main className="w-full md:flex-1 px-5 py-7 md:px-10 md:py-9 min-w-0 max-w-[1200px]">
        {page !== "home" && (
        <header className="flex flex-col md:flex-row md:items-start md:justify-between gap-3 pb-6 mb-7">
          <div className="max-w-2xl">
            <h1 className="text-[26px] font-bold text-ink mb-2 tracking-tightish">
              {page === "motion-lab" ? "动作实验室" : t(`nav.${page}`)}
            </h1>
            <p className="text-[13px] text-muted leading-relaxed">
              {page === "chat"
                ? "文字与语音对话，长回复自动展开；支持语音播报与打断。"
                : page === "character"
                ? "角色卡决定栖灵的身份、声音与唤醒方式；启用一张卡即整套切换生效。"
                : page === "memory"
                ? "用户画像、偏好、项目进度与长期事实的分层管理；配置本地仓库后自动归档。"
                : page === "project"
                ? "项目统一工作区：集中查看项目概览、对话、节点、任务和产物。"
                : page === "reminders"
                ? "管理备忘录与任务提醒；到点后由挂件气泡 + 语音主动提醒。"
                : page === "kb"
                ? "本地知识库（Obsidian）只读检索与库路径配置；记忆会自动归档到库内独立目录。"
                : page === "agents"
                ? "执行器状态、任务队列与运行控制；Codex ACP 真实执行已就绪。"
                : page === "extensions"
                ? "技能与 MCP 扩展：轻任务本地直办，按需接入更多可调用能力。"
                : page === "settings"
                ? "模型与权限、语音能力总开关、性能模式、外观与系统维护。"
                : page === "motion-lab"
                ? "调整每个角色动作的时长、冷却、权重与循环；调好后桌面挂件实时生效。"
                : "版本信息、更新日志、运行环境与本地优先说明。"}
            </p>
          </div>
          <span className={`inline-flex items-center gap-1.5 self-start md:self-auto rounded-full px-3 py-1.5 text-xs font-medium ${
            serviceLost ? "bg-warn-50 text-warn" : serviceOk ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad"
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${serviceLost ? "bg-warn" : serviceOk ? "bg-ok" : "bg-bad"}`} />
            {serviceLost ? "服务已退出" : serviceOk ? "服务正常" : "服务离线"}
          </span>
        </header>
        )}

        {serviceLost ? (
          <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg bg-warn-50 text-warn px-4 py-3 text-sm">
            <span className="font-medium">栖灵已退出</span>
            <span className="text-xs">本地服务已停止，页面不会再更新，可以直接关闭；重新启动栖灵后再点右侧按钮。</span>
            <button
              className="ml-auto border border-warn/40 bg-surface rounded-lg px-3 py-1 text-xs text-warn hover:bg-warn-50 transition-colors cursor-pointer"
              onClick={() => setRetryTick((tick) => tick + 1)}
            >
              重新连接
            </button>
          </div>
        ) : error ? (
          <div className="mb-4 rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm">连接失败：{error}</div>
        ) : null}

        {/* 启动自检：error 阻断式卡片；degraded（带修复入口）可关闭横幅。事实源统一为 /api/health diagnostics。 */}
        {serviceOk && !serviceLost && diagErrors.length > 0 && (
          <div className="mb-4 space-y-2">
            {diagErrors.map((d) => (
              <div key={d.name} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-bad/30 bg-bad-50 text-bad px-4 py-3 text-sm">
                <span className="font-medium">{d.label}不可用</span>
                <span className="text-xs">{d.detail}</span>
                {d.fix_hint && <span className="text-xs opacity-80">{d.fix_hint}</span>}
                {d.fix_action && (
                  <button
                    className="ml-auto border border-bad/40 bg-surface rounded-lg px-3 py-1 text-xs text-bad hover:bg-bad-100 transition-colors cursor-pointer"
                    onClick={() => setPage(d.fix_action === "open_agents" ? "agents" : "settings")}
                  >
                    {d.fix_action === "open_agents" ? "去智能体" : "去设置"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {serviceOk && !serviceLost && diagErrors.length === 0 && diagWarnings.filter((d) => !dismissedDiag[d.name]).length > 0 && (
          <div className="mb-4 space-y-2">
            {diagWarnings
              .filter((d) => !dismissedDiag[d.name])
              .map((d) => (
                <div key={d.name} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg bg-warn-50 text-warn px-4 py-2.5 text-xs">
                  <span className="font-medium">{d.label}</span>
                  <span>{d.detail}</span>
                  {d.fix_action && (
                    <button
                      className="ml-auto border border-warn/40 bg-surface rounded-lg px-2.5 py-1 text-warn hover:bg-warn-100 transition-colors cursor-pointer"
                      onClick={() => setPage(d.fix_action === "open_agents" ? "agents" : "settings")}
                    >
                      {d.fix_action === "open_agents" ? "去智能体" : "去设置"}
                    </button>
                  )}
                  <button
                    className="text-warn/70 hover:text-warn px-1 cursor-pointer"
                    onClick={() => setDismissedDiag((cur) => ({ ...cur, [d.name]: true }))}
                    aria-label="关闭提醒"
                  >
                    ✕
                  </button>
                </div>
              ))}
          </div>
        )}

        {page === "home" && (
          <HomePage
            current={current}
            widgetMessage={widgetState?.message ?? undefined}
            wsOpen={wsOpen}
            serviceOk={serviceOk}
            serviceLost={serviceLost}
            health={health}
            agents={agents}
            session={session}
            events={events}
            runDemo={runDemo}
            runSequence={runSequence}
            demoMsg={demoMsg}
            onNavigate={setPage}
          />
        )}

        {page === "chat" && (
          <ChatPage
            voiceLeaseOwned={voiceLeaseOwned}
            onOpenSettings={() => setPage("settings")}
            events={events}
            targetConversation={pendingConversation}
          />
        )}

        {page === "character" && <CharacterPage />}

        {page === "memory" && <MemoryPage />}

        {page === "project" && <ProjectNodesPage onOpenChat={() => setPage("chat")} />}

        {page === "reminders" && <RemindersPage />}

        {page === "kb" && <KnowledgeBasePage />}

        {page === "agents" && <MyAgentsPage />}

        {page === "extensions" && <ExtensionsPage />}

        {page === "settings" && (
          <SettingsPage />
        )}

        {page === "about" && <AboutPage />}

        {page === "motion-lab" && <MotionLabPage />}
      </main>
    </div>
  );
}
