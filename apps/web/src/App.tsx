import { useCallback, useEffect, useRef, useState } from "react";
import type { CompiledMemory, DocOverview, EventEnvelope, MemoryDoc, SearchHit } from "@deskmate/contracts";
import type { AgentInfo, AgentIntegrationStatus, Task } from "@deskmate/contracts";
import {
  connectEvents,
  addMemoryEntry,
  deleteMemoryEntry,
  fetchAgents,
  fetchHealth,
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
  createPersona,
  fetchPersonas,
  fetchSettings,
  routeTask,
  searchMemories,
  searchObsidian,
  fetchWidgetState,
  publishEvent,
  saveMemoryDoc,
  updatePersona,
  updateSettings,
  type AppSettings,
  type PersonaCard,
  type HealthResponse,
  type SessionResponse,
  type WidgetStatusReport,
} from "./api";
import { DEMO_ACTIONS, STATE_LABEL_ZH } from "./state";
import ChatPage from "./ChatPage";

type PageKey = "home" | "chat" | "memory" | "kb" | "agents" | "settings";

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

const NAV: { key: PageKey; label: string }[] = [
  { key: "home", label: "主页" },
  { key: "chat", label: "对话" },
  { key: "memory", label: "记忆" },
  { key: "kb", label: "知识库" },
  { key: "agents", label: "我的智能体" },
  { key: "settings", label: "设置" },
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

function PlaceholderPage({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="card page-card">
      <h2>{title}</h2>
      <ul className="todo-list">
        {items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ul>
    </section>
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
  const [obsidianQuery, setObsidianQuery] = useState("");
  const [obsidian, setObsidian] = useState<{ available: boolean; path: string; items: { path: string; title: string; matches: string[] }[] }>({ available: false, path: "", items: [] });
  const [status, setStatus] = useState("");
  const [exporting, setExporting] = useState(false);

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
    setResults(await searchMemories(search));
  };

  const runObsidianSearch = async (): Promise<void> => {
    if (!obsidianQuery.trim()) return;
    setObsidian(await searchObsidian(obsidianQuery));
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

  return (
    <section className="memory-page">
      <div className="memory-grid">
        <section className="card memory-list">
          <div className="section-title">
            <h3>记忆概览</h3>
            <button className="text-btn" onClick={() => void reload()}>刷新</button>
          </div>
          <div className="memory-overview">
            {overview.map((item) => (
              <button
                key={`${item.layer}:${item.key}`}
                className={`memory-item ${selected?.layer === item.layer && selected?.key === item.key ? "active" : ""}`}
                onClick={() => setSelected({ layer: item.layer, key: item.key })}
              >
                <b>{item.title}</b>
                <span>{item.layer}/{item.key}</span>
                <em>{item.entry_count} 条</em>
              </button>
            ))}
          </div>
        </section>

        <section className="card memory-editor">
          <div className="section-title">
            <h3>{selected ? `${selected.layer}/${selected.key}` : "未选择记忆"}</h3>
            <div className="memory-actions">
              <button className="text-btn" onClick={() => void addEntry()}>新增条目</button>
              <button className="text-btn" onClick={() => void save()}>保存文档</button>
            </div>
          </div>
          {doc ? (
            <>
              <textarea
                className="memory-markdown"
                value={doc.raw_markdown}
                onChange={(e) => setDoc({ ...doc, raw_markdown: e.target.value })}
              />
              <div className="memory-sections">
                {doc.sections.map((section) => (
                  <div key={section.title} className="memory-section-block">
                    <h4>{section.title}</h4>
                    {section.entries.map((entry) => (
                      <div key={entry.entry_id} className="memory-entry">
                        <div>
                          <b>{entry.text}</b>
                          <div className="muted small">{entry.refs.join(" · ") || "无引用"}</div>
                        </div>
                        <button className="mini-btn" onClick={async () => {
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
          ) : <p className="muted">选择左侧文档查看。</p>}
          {status && <p className="msg-line">{status}</p>}
        </section>
      </div>

      <section className="card memory-tools">
        <div className="memory-tool">
          <h3>记忆检索</h3>
          <div className="search-row">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="输入关键词" />
            <button className="send-btn" onClick={() => void runSearch()}>搜索</button>
          </div>
          {results.map((hit) => (
            <div key={hit.entry_id} className="memory-hit">
              <b>{hit.text}</b>
              <span>{hit.layer}/{hit.key} · {hit.section}</span>
            </div>
          ))}
        </div>

        <div className="memory-tool">
          <h3>注入内容</h3>
          <pre className="memory-compiled">{compiled?.text || "无可注入内容"}</pre>
        </div>

        <div className="memory-tool">
          <h3>Obsidian 只读检索</h3>
          {settings?.memory.mode !== "obsidian_linked" && (
            <div className="notice-banner">当前模式不是 Obsidian 连接，vault 入口已隐藏。</div>
          )}
          {settings?.memory.mode === "export_import" && (
            <>
              <div className="notice-banner">导入导出模式下，本地记忆可直接导出成包，后续再补导入向导。</div>
              <button className="send-btn" onClick={() => void exportMemory()} disabled={exporting}>{exporting ? "导出中…" : "导出记忆包"}</button>
            </>
          )}
          {settings?.memory.mode === "obsidian_linked" && (
            <>
          <div className="search-row">
            <input value={obsidianQuery} onChange={(e) => setObsidianQuery(e.target.value)} placeholder="搜索知识库" />
            <button className="send-btn" onClick={() => void runObsidianSearch()}>搜索</button>
          </div>
          <p className="muted small">{obsidian.available ? `Vault: ${obsidian.path}` : "Obsidian vault 未配置或不可访问"}</p>
          {obsidian.items.map((item) => (
            <div key={item.path} className="memory-hit">
              <b>{item.title}</b>
              <span>{item.path}</span>
            </div>
          ))}
            </>
          )}
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
    <section className="memory-page">
      <section className="card">
        <div className="section-title">
          <h3>任务路由</h3>
          <button className="text-btn" onClick={() => void reload()}>刷新</button>
        </div>
        <div className="search-row">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入一句话试着分流" />
          <button className="send-btn" onClick={() => void classify()} disabled={loading}>{loading ? "分流中…" : "分流"}</button>
        </div>
        {routing.task && (
          <div className="notice-banner">
            最新路由：{routing.task.category} / {routing.task.risk_level} / {routing.task.status}
          </div>
        )}
      </section>

      <section className="card executor-status-card">
        <div className="section-title">
          <h3>执行器状态</h3>
          <button className="text-btn" onClick={() => void loadAgents()} disabled={agentLoading}>
            {agentLoading ? "刷新中" : "刷新"}
          </button>
        </div>
        {defaultExecutor && <p className="muted small executor-default">默认执行器：{defaultExecutor}</p>}
        {agentError && <div className="error-banner">{agentError}</div>}
        {agentLoading && agentItems.length === 0 ? (
          <p className="muted executor-empty">正在探测执行器…</p>
        ) : agentItems.length === 0 && !agentError ? (
          <p className="muted executor-empty">未返回执行器信息。</p>
        ) : agentItems.length > 0 ? (
          <div className="executor-list">
            {agentItems.map((agent) => {
              const executable = agent.available && agent.integration_status === "ready";
              return (
                <div key={agent.name} className={`executor-item${executable ? "" : " unavailable"}`}>
                  <div className="executor-head">
                    <div className="executor-head-main">
                      <b>{agent.label}</b>
                      <span className="mono executor-name">{agent.name}</span>
                    </div>
                    <span className={`status-label status-${agent.integration_status}`}>
                      {AGENT_STATUS_ZH[agent.integration_status]}
                    </span>
                  </div>
                  {!executable && <span className="executor-warning">尚未接通真实执行</span>}
                  <ul className="executor-meta">
                    <li><span>available</span><b className={agent.available ? "ok-text" : ""}>{agent.available ? "是" : "否"}</b></li>
                    <li><span>版本</span><b>{agent.version ?? "—"}</b></li>
                    <li><span>协议</span><b>{agent.protocol ?? "—"}</b></li>
                  </ul>
                  <p className="executor-detail">{agent.detail || "暂无详情"}</p>
                </div>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className="card">
        <div className="section-title">
          <h3>最近任务</h3>
          <span className="status-label">本地任务台</span>
        </div>
        {taskNotice && <div className="notice-banner">{taskNotice}</div>}
        {taskError && <div className="error-banner">{taskError}</div>}
        <div className="memory-overview">
          {tasks.map((task) => {
            const resolved = resolveRun(task);
            const run = resolved.run;
            const runBusy = busyRun === "run";
            const runActive = Boolean(run && ["queued", "running", "awaiting_approval"].includes(run.status));
            return (
              <div key={task.task_id} className="memory-hit task-item">
                <b>{task.input}</b>
                <span>{task.category} · {task.risk_level} · {task.status} · {task.preferred_executor ?? "—"}</span>
                {!agentLoading && agentItems.length > 0 && !resolved.ready && canStartRun(task) && (
                  <div className="run-blocked" role="status" title={resolved.detail || undefined}>
                    执行器「{resolved.executor || defaultExecutor || "codex"}」当前不可用；已保留任务，修复配置后可刷新运行。
                  </div>
                )}
                {run && (
                  <div className={`run-strip run-${run.status}`}>
                    <span className={`status-label status-${run.status}`}>{RUN_STATUS_ZH[run.status]}</span>
                    <span className="run-meta">
                      {run.executor} · {run.mode}{run.progress ? ` · ${run.progress}` : ""}
                    </span>
                    {run.error && <span className="run-result run-error" title={run.error}>{run.error}</span>}
                    {run.result && !run.error && !runActive && (
                      <span className="run-result" title={run.result}>{run.result}</span>
                    )}
                  </div>
                )}
                {resolved.ready && canStartRun(task) && (
                  <div className="run-controls">
                    <select
                      className="run-mode"
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
                      className="task-action run-start"
                      type="button"
                      disabled={busyRun === "run"}
                      onClick={() => void startRun(task, resolved.executor)}
                    >
                      {runBusy ? "提交中…" : task.status === "failed" ? "重试" : "运行"}
                    </button>
                  </div>
                )}
                {runActive && (
                  <div className="task-actions run-actions">
                    {run?.status === "awaiting_approval" && (
                      <>
                        <button
                          className="task-action approve"
                          type="button"
                          disabled={Boolean(busyRun)}
                          onClick={() => void decideAction(task, "approved")}
                        >
                          批准
                        </button>
                        <button
                          className="task-action reject"
                          type="button"
                          disabled={Boolean(busyRun)}
                          onClick={() => void decideAction(task, "rejected")}
                        >
                          拒绝
                        </button>
                      </>
                    )}
                    <button
                      className="task-action cancel-run"
                      type="button"
                      disabled={Boolean(busyRun)}
                      onClick={() => void stopRun(task)}
                    >
                      取消
                    </button>
                  </div>
                )}
                <div className="manual-group">
                  <span className="manual-label">手工调试</span>
                  <div className="task-actions manual-actions">
                  {TASK_ACTIONS.map((option) => {
                    const isCurrent = task.status === option.status;
                    const isBusy = busyTask?.taskId === task.task_id;
                    const isBusyAction = isBusy && busyTask?.status === option.status;
                    return (
                      <button
                        key={option.status}
                        className={`task-action${isCurrent ? " current" : ""}${isBusyAction ? " busy" : ""}`}
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
  const [personas, setPersonas] = useState<PersonaCard[]>([]);
  const [persona, setPersona] = useState<PersonaCard | null>(null);
  const [apiKeys, setApiKeys] = useState({ llm: "", dashscope: "", minimax: "" });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void Promise.all([fetchSettings(), fetchPersonas()])
      .then(([nextSettings, nextPersonas]) => {
        setSettings(nextSettings);
        setPersonas(nextPersonas);
        setPersona(nextPersonas.find((item) => item.id === nextSettings.active_persona_id) ?? nextPersonas[0] ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "设置加载失败"));
  }, []);

  if (!settings || !persona) {
    return <section className="card page-card"><h2>设置</h2><p className="muted">{error || "加载中…"}</p></section>;
  }

  const save = async (): Promise<void> => {
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const nextPersona = await updatePersona(persona);
      const body: Record<string, unknown> = {
        active_persona_id: nextPersona.id,
        ui_language: settings.ui.language,
        ui_theme: settings.ui.theme,
        permission_level: settings.permission_level,
        memory_mode: settings.memory.mode,
        obsidian_vault_path: settings.memory.obsidian_vault_path,
        llm_provider: settings.llm.provider,
        llm_base_url: settings.llm.base_url,
        llm_model: settings.llm.model,
        voice_enabled: settings.voice.enabled,
        activation_enabled: settings.voice.activation_enabled,
        activation_default_state: settings.voice.activation_default_state,
        voice_speed: nextPersona.voice.speed ?? settings.voice.speed,
        voice_pitch: nextPersona.voice.pitch ?? settings.voice.pitch,
        voice_volume: settings.voice.volume,
        voice_emotion: settings.voice.emotion,
        voice_instruction: settings.voice.instruction,
      };
      if (apiKeys.llm) body.llm_api_key = apiKeys.llm;
      if (apiKeys.dashscope) body.dashscope_api_key = apiKeys.dashscope;
      if (apiKeys.minimax) body.minimax_api_key = apiKeys.minimax;
      const nextSettings = await updateSettings(body);
      setSettings(nextSettings);
      setPersonas((current) => current.map((item) => item.id === nextPersona.id ? nextPersona : item));
      setApiKeys({ llm: "", dashscope: "", minimax: "" });
      setNotice("已保存。新的语音配置已生效。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const switchPersona = (id: string): void => {
    const next = personas.find((item) => item.id === id);
    if (!next || !settings) return;
    setPersona(next);
    setSettings({ ...settings, active_persona_id: next.id });
    setNotice(`已切换到「${next.name}」，点击保存后生效`);
  };

  const newPersona = async (): Promise<void> => {
    const id = window.prompt("请输入角色卡 ID（只允许英文、数字、_、-）", `persona_${personas.length + 1}`);
    if (!id) return;
    const name = window.prompt("请输入角色名称", "新角色");
    if (!name) return;
    try {
      const created = await createPersona({
        id,
        name,
        kind: "assistant",
        description: "新的桌面 AI 工作伙伴",
        personality: ["自然", "亲切"],
        backstory: "",
        language: "zh-CN",
        reply_style: "默认用中文、简洁、适合朗读。",
        avatar: "",
        voice: { provider: "minimax", model: "speech-2.8-hd", voice: "Chinese (Mandarin)_Soft_Girl", speed: 1.05, pitch: 1 },
        activation: { persona_name: name, wake_prefixes: ["你好", "嗨"], sleep_phrases: ["暂时静默", "先别说话", "安静一下"] },
      });
      setPersonas((current) => [...current, created]);
      setPersona(created);
      setSettings({ ...settings, active_persona_id: created.id });
      setNotice(`已创建「${created.name}」，点击保存后启用`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "角色卡创建失败");
    }
  };

  const setVoice = (key: string, value: string): void => {
    setPersona((current) =>
      current
        ? { ...current, voice: { ...current.voice, [key]: key === "speed" || key === "pitch" ? Number(value) : value } }
        : current,
    );
  };

  return (
    <section className="settings-page">
      <div className="settings-intro">
        <div>
          <h2>设置</h2>
          <p className="muted">角色卡决定 DeskMate 的身份、声音和交互方式。</p>
        </div>
        <button className="save-btn" onClick={() => void save()} disabled={saving}>
          {saving ? "保存中…" : "保存设置"}
        </button>
      </div>
      {notice && <div className="notice-banner">{notice}</div>}
      {error && <div className="error-banner">{error}</div>}

      <div className="settings-grid">
        <section className="card settings-section settings-persona">
          <div className="section-title">
            <h3>角色卡</h3>
            <button className="text-btn" onClick={() => void newPersona()}>新建角色卡</button>
          </div>
          <div className="persona-switcher">
            <label>当前角色
              <select value={persona.id} onChange={(e) => switchPersona(e.target.value)}>
                {personas.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}
              </select>
            </label>
            <span className="status-label">本地 YAML</span>
          </div>
          <div className="persona-editor">
            <div className="avatar-placeholder">{persona.name.slice(0, 1)}</div>
            <div className="field-grid">
              <label>角色名称<input value={persona.name} onChange={(e) => setPersona({ ...persona, name: e.target.value })} /><small>唤醒词默认使用这个名称。</small></label>
              <label>角色类型<input value={persona.kind} onChange={(e) => setPersona({ ...persona, kind: e.target.value })} /><small>例如 assistant、cat、secretary。</small></label>
            </div>
          </div>
          <label>一句话介绍<input value={persona.description} onChange={(e) => setPersona({ ...persona, description: e.target.value })} /><small>用于角色在主界面的简介。</small></label>
          <label>性格标签<input value={persona.personality.join("、")} onChange={(e) => setPersona({ ...persona, personality: e.target.value.split(/[、,，]/).map((x) => x.trim()).filter(Boolean) })} /><small>用顿号分隔，例如：自然、可靠、略带幽默。</small></label>
          <label>背景故事<textarea value={persona.backstory} onChange={(e) => setPersona({ ...persona, backstory: e.target.value })} /><small>作为稳定人设背景，不等同于用户记忆。</small></label>
          <label>回复风格<textarea value={persona.reply_style} onChange={(e) => setPersona({ ...persona, reply_style: e.target.value })} /><small>会影响后续对话提示词和语音表达。</small></label>
        </section>

        <section className="card settings-section">
          <div className="section-title"><h3>语音</h3><span className={settings.voice.dashscope_configured || settings.voice.minimax_configured ? "status-label good" : "status-label"}>{settings.voice.dashscope_configured || settings.voice.minimax_configured ? "已配置" : "未配置"}</span></div>
          <label className="switch-row"><span>启用语音</span><input type="checkbox" checked={settings.voice.enabled} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, enabled: e.target.checked } })} /></label>
          <label>音色<input value={persona.voice.voice ?? settings.voice.tts_voice} onChange={(e) => setVoice("voice", e.target.value)} /><small>填写供应商音色 ID；当前默认使用 MiniMax Soft_Girl。</small></label>
          <div className="field-grid">
            <label>语速<input type="number" min="0.5" max="2" step="0.05" value={persona.voice.speed ?? settings.voice.speed} onChange={(e) => setVoice("speed", e.target.value)} /></label>
            <label>音高<input type="number" min="0.5" max="2" step="0.05" value={persona.voice.pitch ?? settings.voice.pitch} onChange={(e) => setVoice("pitch", e.target.value)} /></label>
          </div>
          <label>语音情绪<input value={settings.voice.emotion} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, emotion: e.target.value } })} placeholder="例如 gentle" /><small>可选；不同供应商支持的情绪标签不同。</small></label>
          <label>风格指令<textarea value={settings.voice.instruction} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, instruction: e.target.value } })} placeholder="例如：温柔、自然、语速适中" /><small>用于 TTS 的表现提示，不改变角色卡身份。</small></label>
          <label>MiniMax API key<input type="password" value={apiKeys.minimax} onChange={(e) => setApiKeys({ ...apiKeys, minimax: e.target.value })} placeholder={settings.voice.minimax_configured ? "已配置，输入新值可覆盖" : "未配置"} /><small>只写入本机 data/settings.local.json，不会显示原值。</small></label>
          <label>DashScope API key<input type="password" value={apiKeys.dashscope} onChange={(e) => setApiKeys({ ...apiKeys, dashscope: e.target.value })} placeholder={settings.voice.dashscope_configured ? "已配置，输入新值可覆盖" : "未配置"} /><small>用于 STT；保存后立即刷新服务状态。</small></label>
        </section>

        <section className="card settings-section">
          <div className="section-title"><h3>唤醒与监听</h3><span className="status-label">本地控制</span></div>
          <label className="switch-row"><span>启用语音激活</span><input type="checkbox" checked={settings.voice.activation_enabled} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, activation_enabled: e.target.checked } })} /></label>
          <label>唤醒词角色名<input value={persona.activation.persona_name ?? persona.name} onChange={(e) => setPersona({ ...persona, activation: { ...persona.activation, persona_name: e.target.value } })} /><small>例如“你好，{persona.activation.persona_name ?? persona.name}”。</small></label>
          <label>唤醒前缀<input value={(persona.activation.wake_prefixes ?? ["你好", "嗨"]).join("、")} onChange={(e) => setPersona({ ...persona, activation: { ...persona.activation, wake_prefixes: e.target.value.split(/[、,，]/).map((x) => x.trim()).filter(Boolean) } })} /><small>用顿号分隔多个前缀。</small></label>
          <label>静默指令<input value={(persona.activation.sleep_phrases ?? []).join("、")} onChange={(e) => setPersona({ ...persona, activation: { ...persona.activation, sleep_phrases: e.target.value.split(/[、,，]/).map((x) => x.trim()).filter(Boolean) } })} /><small>说出其中任意一句后，普通语音不会触发对话。</small></label>
          <label>默认状态<select value={settings.voice.activation_default_state} onChange={(e) => setSettings({ ...settings, voice: { ...settings.voice, activation_default_state: e.target.value } })}><option value="listening">常开监听</option><option value="sleeping">静默等待唤醒</option></select></label>
        </section>

        <section className="card settings-section">
          <div className="section-title"><h3>模型与权限</h3><span className="status-label">本地配置</span></div>
          <label>LLM Provider<select value={settings.llm.provider} onChange={(e) => setSettings({ ...settings, llm: { ...settings.llm, provider: e.target.value } })}><option value="auto">自动</option><option value="openai">OpenAI 兼容</option><option value="echo">演示模式</option></select><small>自动模式会根据本地配置选择可用的 Provider。</small></label>
          <label>API 地址<input value={settings.llm.base_url} onChange={(e) => setSettings({ ...settings, llm: { ...settings.llm, base_url: e.target.value } })} placeholder="https://.../v1" /></label>
          <label>模型<input value={settings.llm.model} onChange={(e) => setSettings({ ...settings, llm: { ...settings.llm, model: e.target.value } })} /></label>
          <label>LLM API key<input type="password" value={apiKeys.llm} onChange={(e) => setApiKeys({ ...apiKeys, llm: e.target.value })} placeholder={settings.llm.api_key_configured ? "已配置，输入新值可覆盖" : "未配置"} /></label>
          <label>权限级别<select value={settings.permission_level} onChange={(e) => setSettings({ ...settings, permission_level: e.target.value })}><option value="confirm_risky">高风险操作确认</option><option value="confirm_all">所有外部操作确认</option><option value="read_only">只读模式</option></select><small>当前只影响配置记录，任务授权流将在后续 Step 接入。</small></label>
          <label>记忆模式<select value={settings.memory.mode} onChange={(e) => setSettings({ ...settings, memory: { ...settings.memory, mode: e.target.value } })}><option value="standalone">独立本地</option><option value="obsidian_linked">Obsidian 连接</option><option value="export_import">导入导出</option></select><small>独立本地是默认发布模式；Obsidian 连接只读读取 vault；导入导出保留本地档案，后续可迁移。</small></label>
          {settings.memory.mode === "obsidian_linked" && <label>Obsidian vault 路径<input value={settings.memory.obsidian_vault_path} onChange={(e) => setSettings({ ...settings, memory: { ...settings.memory, obsidian_vault_path: e.target.value } })} placeholder="/Users/.../knowledge" /><small>没有 Obsidian 也可以继续使用，只是这个入口不会启用。</small></label>}
          {settings.memory.mode === "export_import" && <div className="notice-banner">导入导出模式先保留本地记忆档案，后续补导出包和导入入口。</div>}
          <label>界面主题<select value={settings.ui.theme} onChange={(e) => setSettings({ ...settings, ui: { ...settings.ui, theme: e.target.value } })}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色（预留）</option></select></label>
        </section>
      </div>
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState<PageKey>("home");
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
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-dot" />
          DeskMate
          <span className="brand-sub">桌面助理</span>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${page === item.key ? "active" : ""}`}
              onClick={() => setPage(item.key)}
            >
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <footer className="sidebar-footer">Step 7 · Agent 真实执行</footer>
      </aside>

      <main className="content">
        <header className="page-head">
          <div>
            <h1>{page === "home" ? "主页" : NAV.find((n) => n.key === page)?.label}</h1>
            <p>
              {page === "home"
                ? "本地优先的桌面 AI 工作伙伴 —— 挂件即时反馈，主界面承载项目和配置。"
                : "任务分流、项目记忆和角色配置主线已接通；Codex ACP 真实执行可运行，其余执行器持续预留。"}
            </p>
          </div>
          <div className={`chip ${serviceOk ? "ok" : "bad"}`}>
            {serviceOk ? "服务正常" : "服务离线"}
          </div>
        </header>

        {error && <div className="error-banner">连接失败：{error}</div>}

        {page === "home" && (
          <>
            <section className="cards">
              <div className="card">
                <h3>挂件当前状态</h3>
                <div className="state-hero" data-state={current}>
                  <span className="state-dot" />
                  <b>{stateLabel(current)}</b>
                </div>
                <ul className="kv">
                  <li><span>WebSocket</span><b className={wsOpen ? "ok-text" : "muted"}>{wsOpen ? "已连接" : "未连接"}</b></li>
                  <li><span>任务</span><b>{widgetState?.task_id ?? "—"}</b></li>
                  <li><span>说明</span><b className="small">{widgetState?.message ?? "—"}</b></li>
                </ul>
              </div>

              <div className="card">
                <h3>状态演练（Step 2 验证）</h3>
                <div className="demo-grid">
                  {DEMO_ACTIONS.map((a) => (
                    <button key={a.eventType} className="demo-btn" onClick={() => void runDemo(a)}>
                      {a.label}
                    </button>
                  ))}
                </div>
                <button className="demo-btn wide" onClick={() => void runSequence()}>
                  演示完整流程
                </button>
                {demoMsg && <p className="msg-line">{demoMsg}</p>}
                <p className="muted small note">
                  演练事件经 ai-service 广播：挂件与这里会同时收到。
                </p>
              </div>

              <div className="card">
                <h3>本地服务</h3>
                <ul className="kv">
                  <li><span>版本</span><b>v{health?.version ?? "—"}</b></li>
                  <li><span>运行时长</span><b>{health ? fmtUptime(health.uptime_s) : "—"}</b></li>
                  <li><span>运行时</span><b>Python {health?.python ?? "—"}</b></li>
                  <li><span>会话</span><b className="mono small">{session?.session_id ?? "—"}</b></li>
                </ul>
              </div>
            </section>

            <section className="card event-log">
              <h3>最近事件</h3>
              {events.length === 0 ? (
                <p className="muted">暂无事件。点击上方按钮发布一次状态演练。</p>
              ) : (
                <ul>
                  {[...events].reverse().map((ev, i) => (
                    <li key={`${ev.event_id}-${i}`} className="mono small">
                      <span className="ev-type">{ev.event_type}</span>
                      <span className="muted">{ev.task_id ?? ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}

        {page === "chat" && <ChatPage />}

        {page === "memory" && <MemoryPage />}

        {page === "kb" && (
          <PlaceholderPage title="知识库" items={["Obsidian 只读检索", "记忆页已包含本地搜索入口", "后续再接写入和授权流"]} />
        )}

        {page === "agents" && <MyAgentsPage />}

        {page === "settings" && (
          <SettingsPage />
        )}
      </main>
    </div>
  );
}
