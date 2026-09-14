import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { CompiledMemory, DocOverview, EventEnvelope, MemoryDoc, SearchHit } from "@deskmate/contracts";
import type { AgentInfo, AgentIntegrationStatus, Task } from "@deskmate/contracts";
import {
  connectEvents,
  addMemoryEntry,
  deleteMemoryEntry,
  fetchAgents,
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
  routeTask,
  searchMemories,
  searchObsidian,
  fetchMemoryVaultStatus,
  fetchWidgetState,
  publishEvent,
  saveMemoryDoc,
  updateSettings,
  updateAgentConfig,
  type AppSettings,
  type MemoryVaultStatus,
  type HealthResponse,
  type SessionResponse,
  type WidgetStatusReport,
} from "./api";
import { DEMO_ACTIONS, STATE_LABEL_ZH } from "./state";
import ChatPage from "./ChatPage";
import CharacterPage from "./CharacterPage";
import AboutPage from "./AboutPage";
import ModelProfilesSection from "./ModelProfilesSection";

type PageKey = "home" | "chat" | "character" | "memory" | "kb" | "agents" | "settings" | "about";

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
  auth_required: "需登录",
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
  auth_required: { pill: "bg-warn-50 text-warn", dot: "bg-warn animate-pulse", note: "已安装但账号未登录或登录已失效，登录后重新检测。", noteCls: "text-warn" },
  not_installed: { pill: "bg-line-subtle text-muted", dot: "bg-muted", note: "尚未安装；按文档安装后刷新即可使用。", noteCls: "text-muted" },
  error: { pill: "bg-bad-50 text-bad", dot: "bg-bad", note: "接入异常，请检查配置后刷新。", noteCls: "text-bad" },
};
const AGENT_CARD_CLS: Record<AgentIntegrationStatus, string> = {
  ready: "border-line bg-white",
  pending: "border-warn/40 bg-warn-50/40",
  auth_required: "border-warn/40 bg-warn-50/40",
  not_installed: "border-line-subtle bg-surface-tertiary",
  error: "border-bad/40 bg-bad-50/40",
};

const NAV: { key: PageKey; label: string }[] = [
  { key: "home", label: "主页" },
  { key: "chat", label: "对话" },
  { key: "character", label: "角色卡" },
  { key: "memory", label: "记忆" },
  { key: "kb", label: "知识库" },
  { key: "agents", label: "我的智能体" },
  { key: "settings", label: "设置" },
  { key: "about", label: "关于" },
];

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

function stateLabel(state: string): string {
  return STATE_LABEL_ZH[state as keyof typeof STATE_LABEL_ZH] ?? state;
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
      <div className="rounded-lg border border-line bg-white shadow-card">
        <div className="px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-ink">Obsidian 知识库</h3>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${linked ? "bg-ok-50 text-ok" : "bg-warn-50 text-warn"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${linked ? "bg-ok" : "bg-warn"}`} />
              {linked ? "已启用" : "未启用"}
            </span>
          </div>
          <p className="text-xs text-muted leading-relaxed mb-3">
            库路径可填可不填。启用后，记忆页会把本地记忆自动归档到该库的 <code className="font-mono">DeskMate/记忆</code> 独立目录，不影响库内其它内容；记忆本体仍保存在本机。
          </p>
          <label className="flex flex-col gap-1.5 text-xs text-muted mb-3">
            <span>库路径</span>
            <input
              className="w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
              value={draftPath}
              onChange={(e) => setDraftPath(e.target.value)}
              placeholder="/Users/.../knowledge"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2.5">
            {!linked ? (
              <button
                className="h-[38px] px-4 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
                onClick={() => void enableVault()}
                disabled={saving}
              >
                {saving ? "启用中…" : "保存并启用"}
              </button>
            ) : (
              <>
                <button
                  className="h-[38px] px-4 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
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
          {linked && vault && !vault.available && (
            <p className="text-xs text-warn mt-2.5 leading-relaxed">当前路径不可访问或未启用：检索暂不可用。记忆仍保存在本机，可保留该路径稍后修正。</p>
          )}
          {linked && vault?.available && (
            <p className="flex items-center gap-1.5 text-[11px] text-muted mt-2.5 leading-relaxed min-w-0">
              {vault.mirror_dir_exists ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-ok shrink-0" />
                  <span className="min-w-0">自动归档已就绪：库内 <code className="font-mono">DeskMate/记忆</code> 共 {vault.doc_files} 份文档
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
      <div className="rounded-lg border border-line bg-white shadow-card">
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
              className="h-[38px] px-4 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50 disabled:cursor-default"
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
        <div className="rounded-lg border border-line bg-white shadow-card">
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
    const section = window.prompt("小节名称", "项目进度");
    if (!section) return;
    const text = window.prompt("记忆内容", "新的项目记录");
    if (!text) return;
    const next = await addMemoryEntry(selected.layer, selected.key, section, text);
    setDoc(next);
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
      a.download = `deskmate-memory-${new Date().toISOString().slice(0, 10)}.json`;
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
        <section className="rounded-lg border border-line bg-white shadow-card p-4 min-w-0">
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
        <section className="rounded-lg border border-line bg-white shadow-card p-4 min-w-0">
          <div className="flex items-center justify-between gap-2.5 mb-3">
            <h3 className="text-sm font-semibold text-ink min-w-0 break-anywhere">{selected ? `${selected.layer}/${selected.key}` : "未选择记忆"}</h3>
            <div className="flex gap-3 shrink-0">
              <button className="text-brand text-xs hover:underline" onClick={() => void addEntry()}>新增条目</button>
              <button className="text-brand text-xs hover:underline" onClick={() => void save()}>保存文档</button>
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
                        <button className="border border-line bg-white rounded-lg px-2 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors shrink-0" onClick={async () => {
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
      <section className="rounded-lg border border-line bg-white shadow-card p-4 grid grid-cols-1 md:grid-cols-3 gap-3.5">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink mb-2.5">记忆检索</h3>
          <div className="flex gap-2 items-center">
            <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="输入关键词" />
            <button className="h-[38px] px-3.5 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors" onClick={() => void runSearch()}>搜索</button>
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
              <button className="h-[38px] self-start px-3.5 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50" onClick={() => void exportMemory()} disabled={exporting}>{exporting ? "导出中…" : "导出记忆包"}</button>
            </div>
          )}
          {memMode === "obsidian_linked" && vaultConfigured && (
            <>
              <div className="flex gap-2 items-center">
                <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={obsidianQuery} onChange={(e) => setObsidianQuery(e.target.value)} placeholder="搜索知识库" />
                <button className="h-[38px] px-3.5 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors" onClick={() => void runObsidianSearch()}>搜索</button>
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
                    <span className="min-w-0">已连接本地仓库：记忆自动归档到 <code className="font-mono">DeskMate/记忆</code>（{vaultStatus.doc_files} 份文档
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
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configNotice, setConfigNotice] = useState("");

  const loadAgents = async (): Promise<void> => {
    setAgentLoading(true);
    setAgentError("");
    try {
      const data = await fetchAgents();
      setAgentItems(data.items);
      setDefaultExecutor(data.default_executor);
    } catch (e) {
      setAgentError(e instanceof Error ? `执行器状态获取失败：${e.message}` : "执行器状态获取失败");
    } finally {
      setAgentLoading(false);
    }
  };

  const openAgentConfig = async (name: string): Promise<void> => {
    setConfigName(name);
    setConfigCommand("");
    setConfigError("");
    setConfigNotice("");
    try {
      const data = await fetchAgentConfig();
      const entry = data.items.find((item) => item.name === name);
      const value = entry?.config?.[`${name}_command`];
      setConfigCommand(typeof value === "string" ? value : "");
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : "配置读取失败");
    }
  };

  const closeAgentConfig = (): void => {
    setConfigName(null);
    setConfigCommand("");
    setConfigError("");
    setConfigNotice("");
  };

  const saveAgentConfig = async (name: string, commandOverride?: string | null): Promise<void> => {
    const command = commandOverride !== undefined ? commandOverride : configCommand.trim() || null;
    setConfigSaving(true);
    setConfigError("");
    setConfigNotice("");
    try {
      const updated = await updateAgentConfig(name, { command });
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

  const startRun = async (task: Task, executor: string | null): Promise<void> => {
    if (busyRun) return;
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
    if (!run || busyRun) return;
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
    if (!run || busyRun) return;
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
      <section className="rounded-lg border border-line bg-white shadow-card p-4">
        <div className="flex items-center justify-between gap-2.5 mb-3">
          <h3 className="text-sm font-semibold text-ink">任务路由</h3>
          <button className="text-brand text-xs hover:underline" onClick={() => void reload()}>刷新</button>
        </div>
        <div className="flex gap-2 items-center">
          <input className="flex-1 min-w-0 border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20" value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入一句话试着分流" />
          <button className="h-[38px] px-3.5 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50" onClick={() => void classify()} disabled={loading}>{loading ? "分流中…" : "分流"}</button>
        </div>
        {routing.task && (
          <div className="mt-3 rounded-lg border border-ok/30 bg-ok-50 px-3 py-2.5 text-xs text-ok">
            最新路由：{routing.task.category} / {routing.task.risk_level} / {routing.task.status}
          </div>
        )}
      </section>

      {/* Executor status card */}
      <section className="rounded-lg border border-line bg-white shadow-card p-4 min-w-0">
        <div className="flex items-center justify-between gap-2.5 mb-3">
          <h3 className="text-sm font-semibold text-ink">执行器状态</h3>
          <button className="text-brand text-xs hover:underline" onClick={() => void loadAgents()} disabled={agentLoading}>
            {agentLoading ? "刷新中" : "刷新"}
          </button>
        </div>
        {defaultExecutor && <p className="text-xs text-muted mb-1.5 break-anywhere">默认执行器：<code className="font-mono">{defaultExecutor}</code></p>}
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
              const pill = AGENT_PILL[st];
              return (
                <div key={agent.name} className={`min-w-0 border rounded-lg p-3 ${AGENT_CARD_CLS[st]}`}>
                  <div className="flex items-start justify-between gap-2.5">
                    <div className="min-w-0">
                      <b className="block text-sm leading-tight break-anywhere">{agent.label}</b>
                      <span className="block mt-0.5 text-[11px] text-muted font-mono break-all">{agent.name}</span>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${pill.pill}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${pill.dot}`} />
                      {AGENT_STATUS_ZH[st]}
                    </span>
                  </div>
                  <p className={`text-[11px] leading-relaxed mt-1.5 ${pill.noteCls}`}>{pill.note}</p>
                  <ul className="list-none flex flex-wrap gap-x-3 gap-y-1 mt-2 text-xs">
                    <li><span className="text-muted">available</span> <b className={agent.available ? "text-ok" : "text-bad"}>{agent.available ? "是" : "否"}</b></li>
                    <li><span className="text-muted">版本</span> <b>{agent.version ?? "—"}</b></li>
                    <li><span className="text-muted">协议</span> <b>{agent.protocol ?? "—"}</b></li>
                  </ul>
                  {agent.detail && <p className="text-xs text-muted mt-2 leading-relaxed break-anywhere">{agent.detail}</p>}
                  {(agent.name === "codex" || agent.name === "workbuddy") && (
                    configName === agent.name ? (
                      <div className="mt-2.5 border-t border-line pt-2.5 flex flex-col gap-2 min-w-0">
                        <div>
                          <p className="text-[11px] text-muted mb-1">{agent.label} 可执行文件路径</p>
                          <input
                            className="w-full border border-line rounded-md px-2 py-1.5 text-xs font-mono text-ink bg-white focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20"
                            value={configCommand}
                            onChange={(e) => setConfigCommand(e.target.value)}
                            placeholder="留空 = 自动检测"
                          />
                          <p className="text-[11px] text-muted mt-1">留空保存即恢复自动检测。</p>
                        </div>
                        {configNotice && <p className="text-[11px] text-ok">{configNotice}</p>}
                        {configError && <p className="text-[11px] text-bad break-anywhere">{configError}</p>}
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="px-2.5 py-1 rounded-md bg-brand text-white text-xs font-medium hover:bg-brand-600 transition-colors disabled:opacity-50"
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
                        <button
                          className="px-2.5 py-1 rounded-md border border-line text-xs text-ink hover:bg-surface-secondary transition-colors shrink-0"
                          onClick={() => void openAgentConfig(agent.name)}
                        >
                          配置
                        </button>
                      </div>
                    )
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
      </section>

      {/* Recent tasks card */}
      <section className="rounded-lg border border-line bg-white shadow-card p-4">
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
                              : "bg-white border-line text-ink hover:border-brand hover:text-brand"
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
      <section className="rounded-lg border border-line bg-white shadow-card p-4">
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
  const cardCls = "rounded-lg border border-line bg-white shadow-card p-4 flex flex-col gap-3 min-w-0";

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted leading-relaxed">系统级配置集中在此；角色相关的形象、语音与唤醒请在「角色卡」页编辑。</p>
        <div className="flex items-center gap-3 shrink-0">
          {notice && <span className="text-sm text-ok">{notice}</span>}
          {error && <span className="text-sm text-bad">{error}</span>}
          <button
            className="px-4 py-2 text-sm font-medium rounded-lg bg-brand text-white hover:bg-brand-600 transition-colors disabled:opacity-50"
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
          <small className="text-[11px] text-muted -mt-1">关闭后语音输入仍可用，回复不自动朗读（任务待确认提醒的语音播报一并关闭）；消息下方 🔊 仍可手动播报。</small>
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
            <select className={inputCls} value={settings.ui.theme} onChange={(e) => setSettings({ ...settings, ui: { ...settings.ui, theme: e.target.value } })}>
              <option value="system">跟随系统</option>
              <option value="light">浅色</option>
              <option value="dark">深色（预留）</option>
            </select>
            <small className="text-[11px] text-muted">界面语言跟随系统，后续版本提供独立选项。</small>
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

function fmtClock(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function performanceInfo(mode: HealthResponse["performance_mode"] | undefined): { label: string; cls: string; hint: string } {
  switch (mode) {
    case "quality":
      return { label: "高质量", cls: "bg-brand-100 text-brand", hint: "全功能：语音、动画与录制均启用。" };
    case "balanced":
      return { label: "均衡", cls: "bg-ok-50 text-ok", hint: "默认模式：语音启用，动画使用简单状态切换。" };
    case "lite":
      return { label: "轻量", cls: "bg-line-subtle text-muted", hint: "仅文字，关闭语音与动画。" };
    default:
      return { label: "—", cls: "bg-line-subtle text-muted", hint: "服务未返回性能模式信息。" };
  }
}

function HomeStatusSection({ health, serviceOk }: { health: HealthResponse | null; serviceOk: boolean }) {
  const vp = health?.voice_pipeline;
  const mem = health?.memory_stats;
  const activity = health?.recent_activity ?? [];
  const perf = performanceInfo(health?.performance_mode);
  const dataOk = serviceOk && !!vp && !!mem;
  const dotCls = (ok: boolean | undefined, neutralOff = false): string => {
    if (ok === undefined) return "bg-muted";
    return ok ? "bg-ok" : neutralOff ? "bg-muted" : "bg-bad";
  };
  const rowValue = (ok: boolean | undefined, onLabel: string, offLabel: string): string => {
    if (ok === undefined) return "—";
    return ok ? onLabel : offLabel;
  };

  return (
    <section className="rounded-lg border border-line bg-white shadow-card overflow-hidden">
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-ink">系统状态</h3>
          <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${serviceOk ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad"}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${serviceOk ? "bg-ok" : "bg-bad"}`} />
            {serviceOk ? "运行中" : "离线"}
          </span>
        </div>
        <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 ${dataOk ? "" : "opacity-60"}`}>
          <div className="rounded-lg bg-surface-secondary p-3.5">
            <div className="text-xs font-semibold text-ink mb-2.5">本地服务</div>
            <div className="space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted">状态</span>
                <span className="inline-flex items-center gap-1.5 font-medium text-ink">
                  <span className={`w-1.5 h-1.5 rounded-full ${serviceOk ? "bg-ok" : "bg-bad"}`} />
                  {serviceOk ? "运行中" : "离线"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">运行时长</span>
                <span className="font-medium text-ink">{health ? fmtUptime(health.uptime_s) : "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">版本</span>
                <span className="font-medium text-ink">v{health?.version ?? "—"}</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg bg-surface-secondary p-3.5">
            <div className="text-xs font-semibold text-ink mb-2.5">语音链路</div>
            <div className="space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-muted"><span className={`w-1.5 h-1.5 rounded-full ${dotCls(vp?.stt_ready)}`} />STT</span>
                <span className="font-medium text-ink">{rowValue(vp?.stt_ready, "就绪", "不可用")}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-muted"><span className={`w-1.5 h-1.5 rounded-full ${dotCls(vp?.tts_ready)}`} />TTS</span>
                <span className="font-medium text-ink">{rowValue(vp?.tts_ready, "就绪", "不可用")}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-muted"><span className={`w-1.5 h-1.5 rounded-full ${dotCls(vp?.vad_working, true)}`} />VAD</span>
                <span className="font-medium text-ink">{rowValue(vp?.vad_working, "监听中", "未监听")}</span>
              </div>
            </div>
            {vp?.degradation_reason && <div className="mt-2 text-[11px] text-warn leading-relaxed">降级原因：{vp.degradation_reason}</div>}
          </div>

          <div className="rounded-lg bg-surface-secondary p-3.5">
            <div className="text-xs font-semibold text-ink mb-2.5">记忆</div>
            <div className="space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-muted"><span className={`w-1.5 h-1.5 rounded-full ${dotCls(mem?.obsidian_linked, true)}`} />Obsidian</span>
                <span className="font-medium text-ink">{rowValue(mem?.obsidian_linked, "已连接", "未连接")}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">记忆条目</span>
                <span className="font-medium text-ink">{mem?.total_entries != null ? `${mem.total_entries} 条` : "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">上次编译</span>
                <span className="font-medium text-ink">{mem?.last_compile ? fmtClock(mem.last_compile) : "—"}</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg bg-surface-secondary p-3.5">
            <div className="text-xs font-semibold text-ink mb-2.5">性能模式</div>
            <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${perf.cls}`}>{perf.label}</span>
            <p className="text-[11px] text-muted mt-2 leading-relaxed">{perf.hint}</p>
          </div>
        </div>

        <div className="mt-4 border-t border-line pt-3.5">
          <div className="text-xs font-semibold text-ink mb-2">最近活动</div>
          {activity.length === 0 ? (
            <p className="text-xs text-muted">{serviceOk ? "暂无活动" : "服务离线，暂无活动"}</p>
          ) : (
            <ul className="space-y-1.5">
              {activity.slice(0, 5).map((item, i) => (
                <li key={`${item.timestamp}-${i}`} className="flex items-center gap-3 px-3 py-1.5 rounded-md bg-surface-tertiary min-w-0">
                  <span className="text-[11px] text-muted font-mono shrink-0">{fmtClock(item.timestamp)}</span>
                  <span className="text-xs font-semibold text-brand font-mono shrink-0">{item.event_type}</span>
                  <span className="flex-1 min-w-0 text-xs text-ink truncate">{item.summary}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function ExecutorStatusSection({ agents }: { agents: AgentInfo[] }) {
  if (!agents || agents.length === 0) {
    return null;
  }

  const readyCount = agents.filter(a => a.integration_status === 'ready').length;
  const totalCount = agents.length;

  return (
    <section className="rounded-lg border border-line bg-white shadow-card overflow-hidden">
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-ink">执行器状态</h3>
          <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${
            readyCount > 0 ? 'bg-ok-50 text-ok' : 'bg-warn-50 text-warn'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${readyCount > 0 ? 'bg-ok' : 'bg-warn'}`} />
            {readyCount}/{totalCount} 可用
          </span>
        </div>
        <div className="space-y-2">
          {agents.map((agent) => {
            const statusInfo = AGENT_PILL[agent.integration_status];
            return (
              <div key={agent.name} className="flex items-center justify-between py-2 border-b border-line-subtle last:border-b-0">
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${statusInfo.dot}`} />
                  <span className="text-sm font-medium text-ink">{agent.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs ${statusInfo.noteCls}`}>
                    {AGENT_STATUS_ZH[agent.integration_status]}
                  </span>
                  {agent.version && (
                    <span className="text-xs text-muted font-mono">v{agent.version}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {readyCount === 0 && (
          <div className="mt-3 p-3 rounded-lg bg-warn-50 border border-warn/20">
            <p className="text-xs text-warn leading-relaxed">
              没有可用的执行器。请在「我的智能体」页面配置并启用至少一个执行器。
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState<PageKey>("home");
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [voiceLeaseOwned, setVoiceLeaseOwned] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [widgetState, setWidgetState] = useState<WidgetStatusReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demoMsg, setDemoMsg] = useState("");
  const stopRef = useRef<(() => void) | undefined>(undefined);

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
    if (page !== "chat") {
      setVoiceLeaseOwned(false);
      return;
    }

    let alive = true;
    let heartbeatTimer: number | undefined;
    let retryTimer: number | undefined;

    const acquire = async (): Promise<void> => {
      const acquired = await acquireVoiceLease();
      if (!alive) return;
      setVoiceLeaseOwned(acquired);
      if (!acquired) {
        retryTimer = window.setTimeout(() => void acquire(), 4000);
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
  }, [page]);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const [h, s] = await Promise.all([fetchHealth(), fetchSession()]);
        if (!alive) return;
        setHealth(h);
        setSession(s);
        setError(null);
        const ws = await fetchWidgetState();
        if (alive && ws) setWidgetState(ws);
        if (!stopRef.current) {
          stopRef.current = connectEvents(s.ws_url, onEvent, setWsOpen);
        }
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "无法连接本地服务");
        setWsOpen(false);
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
  }, [onEvent]);

  const serviceOk = health?.status === "ok";
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

  return (
    <div className="flex flex-col md:flex-row min-h-screen bg-surface-secondary">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-56 bg-white border-r border-line px-3 py-5 shrink-0">
        <div className="flex items-center gap-2 px-3 mb-6">
          <span className="w-3 h-3 rounded-full bg-brand shadow-[0_0_0_4px_rgba(79,110,247,0.16)]" />
          <span className="text-lg font-semibold text-ink">DeskMate</span>
          <span className="text-xs text-muted">桌面助理</span>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                page === item.key
                  ? "bg-brand-100 text-brand font-semibold"
                  : "text-ink hover:bg-brand-50"
              }`}
              onClick={() => setPage(item.key)}
            >
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="mt-auto px-3 pt-4 text-[11px] text-muted">Step 9 · V1 打磨</div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden flex items-center gap-2 px-3 py-2.5 bg-white border-b border-line overflow-x-auto w-full shrink-0">
        <span className="flex items-center gap-1.5 mr-2 whitespace-nowrap">
          <span className="w-2.5 h-2.5 rounded-full bg-brand" />
          <b className="text-sm">DeskMate</b>
        </span>
        {NAV.map((item) => (
          <button
            key={item.key}
            className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors ${
              page === item.key
                ? "bg-brand-100 text-brand font-semibold"
                : "text-ink hover:bg-brand-50"
            }`}
            onClick={() => setPage(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <main className="w-full md:flex-1 px-5 py-7 md:px-8 min-w-0">
        <header className="flex flex-col md:flex-row md:items-start md:justify-between gap-3 pb-6 mb-6 border-b border-line">
          <div>
            <h1 className="text-2xl font-bold text-ink mb-1.5">
              {page === "home" ? "主页" : NAV.find((n) => n.key === page)?.label}
            </h1>
            <p className="text-sm text-muted leading-relaxed">
              {page === "home"
                ? "本地优先的桌面 AI 工作伙伴 —— 挂件即时反馈，主界面承载项目和配置。"
                : page === "chat"
                ? "文字与语音对话，长回复自动展开；支持语音播报与打断。"
                : page === "character"
                ? "角色卡决定 DeskMate 的身份、声音与唤醒方式；启用一张卡即整套切换生效。"
                : page === "memory"
                ? "用户画像、偏好、项目进度与长期事实的分层管理；配置本地仓库后自动归档。"
                : page === "kb"
                ? "本地知识库（Obsidian）只读检索与库路径配置；记忆会自动归档到库内独立目录。"
                : page === "agents"
                ? "执行器状态、任务队列与运行控制；Codex ACP 真实执行已就绪。"
                : page === "settings"
                ? "模型与权限、语音能力总开关、性能模式、外观与系统维护。"
                : "版本信息、更新日志、运行环境与本地优先说明。"}
            </p>
          </div>
          <span className={`inline-flex items-center self-start md:self-auto rounded-full px-3.5 py-1.5 text-xs font-medium ${
            serviceOk ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad"
          }`}>
            {serviceOk ? "服务正常" : "服务离线"}
          </span>
        </header>

        {error && (
          <div className="mb-4 rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm">连接失败：{error}</div>
        )}

        {page === "home" && (
          <div className="flex flex-col gap-5">
            {/* Top row: Widget state + Service info */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Widget status card */}
              <div className="rounded-lg border border-line bg-white shadow-card overflow-hidden">
                <div className="px-5 pt-5 pb-3">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-ink">挂件状态</h3>
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-brand-100 text-brand">
                      {current}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 bg-surface-secondary rounded-lg p-4 mb-4">
                    <div className="relative">
                      <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-brand to-purple-500 flex items-center justify-center text-white text-2xl font-bold shadow-md">
                        DM
                      </div>
                      <div className={`absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full border-2 border-white ${current === "executing" ? "bg-amber-400 animate-pulse" : current === "completed" ? "bg-ok" : current === "listening" ? "bg-blue-500 animate-breathe" : current === "awaiting_approval" ? "bg-orange-500 animate-pulse" : "bg-muted"}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-base font-semibold text-ink">{stateLabel(current)}</div>
                      <div className="text-sm text-muted truncate mt-0.5">{widgetState?.message ?? "等待中"}</div>
                    </div>
                  </div>
                </div>
                <div className="border-t border-line px-5 py-3">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="text-center">
                      <div className="text-xs text-muted mb-1">WebSocket</div>
                      <div className={`text-sm font-semibold ${wsOpen ? "text-ok" : "text-muted"}`}>
                        {wsOpen ? "已连接" : "未连接"}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-muted mb-1">任务</div>
                      <div className="text-sm font-semibold text-ink truncate">
                        {widgetState?.task_id ?? "—"}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-muted mb-1">会话</div>
                      <div className="text-sm font-semibold text-ink font-mono truncate text-xs leading-6">
                        {session?.session_id?.slice(0, 8) ?? "—"}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Service info card */}
              <div className="rounded-lg border border-line bg-white shadow-card">
                <div className="px-5 pt-5 pb-3">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-ink">本地服务</h3>
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${serviceOk ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad"}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${serviceOk ? "bg-ok" : "bg-bad"}`} />
                      {serviceOk ? "运行中" : "离线"}
                    </span>
                  </div>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted">版本</span>
                      <span className="text-sm font-semibold text-ink">v{health?.version ?? "—"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted">运行时长</span>
                      <span className="text-sm font-semibold text-ink">{health ? fmtUptime(health.uptime_s) : "—"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted">运行时</span>
                      <span className="text-sm font-semibold text-ink">Python {health?.python ?? "—"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted">会话 ID</span>
                      <span className="text-xs font-mono text-muted text-right break-all max-w-[65%] min-w-0">{session?.session_id ?? "—"}</span>
                    </div>
                  </div>
                </div>
                <div className="border-t border-line px-5 py-3 bg-surface-tertiary">
                  <div className="text-xs text-muted">
                    本地优先 · 数据不离开设备
                  </div>
                </div>
              </div>
            </div>

            {/* System status dashboard */}
            <ExecutorStatusSection agents={agents} />
            <HomeStatusSection health={health} serviceOk={serviceOk} />

            {/* Demo controls */}
            <div className="rounded-lg border border-line bg-white shadow-card">
              <div className="px-5 pt-4 pb-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-ink">状态演练</h3>
                  <span className="text-xs text-muted">Step 2 验证</span>
                </div>
                <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-3">
                  {DEMO_ACTIONS.map((a) => (
                    <button
                      key={a.eventType}
                      className="px-3 py-2 text-xs font-medium rounded-lg border border-line bg-surface-tertiary text-ink hover:border-brand hover:text-brand hover:bg-brand-50 transition-colors cursor-pointer"
                      onClick={() => void runDemo(a)}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    className="px-4 py-2 text-xs font-medium rounded-lg bg-brand text-white hover:bg-brand-600 transition-colors cursor-pointer"
                    onClick={() => void runSequence()}
                  >
                    演示完整流程
                  </button>
                  {demoMsg && <span className="text-sm text-ok">{demoMsg}</span>}
                </div>
              </div>
            </div>

            {/* Event log */}
            <div className="rounded-lg border border-line bg-white shadow-card">
              <div className="px-5 pt-4 pb-4">
                <h3 className="text-sm font-semibold text-ink mb-3">最近事件</h3>
                {events.length === 0 ? (
                  <p className="text-sm text-muted">暂无事件。点击上方按钮发布一次状态演练。</p>
                ) : (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {[...events].reverse().map((ev, i) => (
                      <div key={`${ev.event_id}-${i}`} className="flex items-center justify-between px-3 py-2 rounded-md bg-surface-tertiary hover:bg-surface-secondary transition-colors">
                        <span className="text-xs font-semibold text-brand font-mono">{ev.event_type}</span>
                        <span className="text-xs text-muted">{ev.task_id ?? ""}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {page === "chat" && (
          <ChatPage voiceLeaseOwned={voiceLeaseOwned} onOpenSettings={() => setPage("settings")} />
        )}

        {page === "character" && <CharacterPage />}

        {page === "memory" && <MemoryPage />}

        {page === "kb" && <KnowledgeBasePage />}

        {page === "agents" && <MyAgentsPage />}

        {page === "settings" && (
          <SettingsPage />
        )}

        {page === "about" && <AboutPage />}
      </main>
    </div>
  );
}
