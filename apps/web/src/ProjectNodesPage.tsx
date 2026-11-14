import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentInfo, ProjectNode, ProjectNodeKind, ProjectNodeStatus, WorkbenchItem, WorkbenchNote, WorkbenchTodo } from "@qiling/contracts";
import {
  createProjectNode,
  deleteProjectNode,
  updateProjectNode,
  fetchConversations,
  fetchProjectNodes,
  fetchRuns,
  fetchTasks,
  fetchAgents,
  fetchTaskRun,
  executeTask,
  cancelRun,
  decideRun,
  createWorkbenchNote,
  updateWorkbenchNote,
  createWorkbenchTodo,
  deleteWorkbenchNote,
  deleteWorkbenchTodo,
  createWorkbenchItem,
  updateWorkbenchItem,
  deleteWorkbenchItem,
  fetchWorkbenchItems,
  fetchWorkbenchNotes,
  fetchWorkbenchTodos,
  updateWorkbenchTodo,
  routeTask,
  type AgentRun,
  type AgentRunMode,
  type ConversationSummary,
} from "./api";

const STATUS_LABEL: Record<ProjectNodeStatus, string> = {
  planned: "计划中",
  in_progress: "进行中",
  completed: "已完成",
  blocked: "已阻塞",
  pending_confirmation: "待确认",
  cancelled: "已取消",
};

const STATUS_CLASS: Record<ProjectNodeStatus, string> = {
  planned: "border-line bg-surface-tertiary",
  in_progress: "border-brand/40 bg-brand-50",
  completed: "border-ok/30 bg-ok-50",
  blocked: "border-bad/30 bg-bad-50",
  pending_confirmation: "border-warn/30 bg-warn-50",
  cancelled: "border-line bg-surface-tertiary opacity-70",
};

const KIND_LABEL: Record<ProjectNodeKind, string> = {
  project: "项目",
  phase: "阶段",
  node: "节点",
  task: "任务",
  artifact: "产物",
  decision: "决策",
  blocker: "阻塞",
  next_step: "下一步",
};

type Draft = {
  title: string;
  kind: ProjectNodeKind;
  status: ProjectNodeStatus;
  parent_id: string;
  next_step: string;
  task_ids: string[];
};

type WorkspaceTab = "overview" | "conversations" | "nodes" | "tasks" | "files";

const PROJECT_PATH_KEY = "qiling.current.project.path";
// 改名前的键：只读回退，避免旧数据读不到
const LEGACY_PROJECT_PATH_KEYS = ["qiling.project.nodes.path", "deskmate.current.project.path", "deskmate.project.nodes.path"];

function readSavedProjectPath(): string {
  for (const key of [PROJECT_PATH_KEY, ...LEGACY_PROJECT_PATH_KEYS]) {
    const value = localStorage.getItem(key);
    if (value) return value;
  }
  return "";
}

const EMPTY_DRAFT: Draft = {
  title: "",
  kind: "node",
  status: "planned",
  parent_id: "",
  next_step: "",
  task_ids: [],
};

function nodeDepth(node: ProjectNode, byId: Map<string, ProjectNode>): number {
  let depth = 0;
  const seen = new Set<string>();
  let parent = node.parent_id ? byId.get(node.parent_id) : undefined;
  while (parent && !seen.has(parent.node_id) && depth < 8) {
    seen.add(parent.node_id);
    depth += 1;
    parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
  }
  return depth;
}

function ProjectNodeCard({
  node,
  onEdit,
  onDelete,
}: {
  node: ProjectNode;
  onEdit: (node: ProjectNode) => void;
  onDelete: (node: ProjectNode) => void;
}) {
  return (
    <article className={`min-w-[220px] max-w-[300px] rounded-lg border p-3 shadow-card ${STATUS_CLASS[node.status]}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-muted">{KIND_LABEL[node.kind]}</div>
          <h3 className="mt-1 text-sm font-semibold text-ink break-words">{node.title}</h3>
        </div>
        <span className="shrink-0 rounded-full bg-surface/70 px-2 py-0.5 text-[10px] text-muted">
          {STATUS_LABEL[node.status]}
        </span>
      </div>
      {node.next_step && <p className="mt-2 text-xs text-muted break-words">下一步：{node.next_step}</p>}
      {node.blocker && <p className="mt-2 text-xs text-bad break-words">阻塞：{node.blocker}</p>}
      {node.task_ids.length > 0 && <p className="mt-2 text-[10px] text-muted">关联任务 {node.task_ids.length} 个</p>}
      <div className="mt-2 flex items-center justify-end gap-2 border-t border-line-subtle pt-2">
        <button className="text-[11px] text-brand hover:underline" onClick={() => onEdit(node)} type="button">编辑</button>
        <button className="text-[11px] text-muted hover:text-bad" onClick={() => onDelete(node)} type="button">删除</button>
      </div>
    </article>
  );
}

function FlowView({
  nodes,
  onEdit,
  onDelete,
}: {
  nodes: ProjectNode[];
  onEdit: (node: ProjectNode) => void;
  onDelete: (node: ProjectNode) => void;
}) {
  const byId = useMemo(() => new Map(nodes.map((node) => [node.node_id, node])), [nodes]);
  const rows = useMemo(() => {
    const grouped = new Map<number, ProjectNode[]>();
    for (const node of nodes) {
      const depth = nodeDepth(node, byId);
      grouped.set(depth, [...(grouped.get(depth) ?? []), node]);
    }
    return [...grouped.entries()].sort(([a], [b]) => a - b);
  }, [byId, nodes]);

  if (nodes.length === 0) {
    return <div className="rounded-lg border border-dashed border-line px-4 py-12 text-center text-sm text-muted">暂无节点，先添加一个项目阶段或任务。</div>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface-secondary p-4">
      <div className="flex min-w-max flex-col gap-4">
        {rows.map(([depth, row], rowIndex) => (
          <div key={depth} className="flex items-center gap-3">
            {rowIndex > 0 && <span className="w-5 text-center text-muted" aria-hidden="true">↓</span>}
            <div className="flex flex-wrap items-center gap-3">
              {row.map((node, index) => (
                <div key={node.node_id} className="flex items-center gap-3">
                  <ProjectNodeCard node={node} onEdit={onEdit} onDelete={onDelete} />
                  {index < row.length - 1 && <span className="text-muted" aria-hidden="true">→</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TreeView({
  nodes,
  onEdit,
  onDelete,
}: {
  nodes: ProjectNode[];
  onEdit: (node: ProjectNode) => void;
  onDelete: (node: ProjectNode) => void;
}) {
  const byParent = useMemo(() => {
    const groups = new Map<string, ProjectNode[]>();
    for (const node of nodes) {
      const key = node.parent_id ?? "";
      groups.set(key, [...(groups.get(key) ?? []), node]);
    }
    return groups;
  }, [nodes]);

  const render = (parentId: string, depth = 0): JSX.Element[] =>
    (byParent.get(parentId) ?? []).flatMap((node) => [
      <div key={node.node_id} className="flex flex-col gap-1.5" style={{ marginLeft: depth * 18 }}>
        <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2">
          <span className={`h-2 w-2 rounded-full ${node.status === "completed" ? "bg-ok" : node.status === "blocked" ? "bg-bad" : "bg-brand"}`} />
          <span className="text-xs text-muted">{KIND_LABEL[node.kind]}</span>
          <b className="min-w-0 break-words text-sm text-ink">{node.title}</b>
          <span className="ml-auto shrink-0 text-[10px] text-muted">{STATUS_LABEL[node.status]}</span>
          <button className="shrink-0 text-[11px] text-brand hover:underline" onClick={() => onEdit(node)} type="button">编辑</button>
          <button className="shrink-0 text-[11px] text-muted hover:text-bad" onClick={() => onDelete(node)} type="button">删除</button>
        </div>
        {render(node.node_id, depth + 1)}
      </div>,
    ]);

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-secondary p-4">
      {render("")}
      {nodes.length === 0 && <p className="py-8 text-center text-sm text-muted">暂无节点。</p>}
    </div>
  );
}

export default function ProjectNodesPage({
  defaultProject,
  onOpenChat,
}: {
  defaultProject?: string;
  onOpenChat?: () => void;
}) {
  const [project, setProject] = useState(
    () => readSavedProjectPath(),
  );
  const [draftPath, setDraftPath] = useState(project);
  const [nodes, setNodes] = useState<ProjectNode[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [defaultExecutor, setDefaultExecutor] = useState("");
  const [runModes, setRunModes] = useState<Record<string, AgentRunMode>>({});
  const [busyRunTask, setBusyRunTask] = useState("");
  const [tasks, setTasks] = useState<Awaited<ReturnType<typeof fetchTasks>>>([]);
  const [workbenchItems, setWorkbenchItems] = useState<WorkbenchItem[]>([]);
  const [notes, setNotes] = useState<WorkbenchNote[]>([]);
  const [todos, setTodos] = useState<WorkbenchTodo[]>([]);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [editingNoteId, setEditingNoteId] = useState("");
  const [todoTitle, setTodoTitle] = useState("");
  const [taskInput, setTaskInput] = useState("");
  const [itemTitle, setItemTitle] = useState("");
  const [itemUrl, setItemUrl] = useState("");
  const [itemGroup, setItemGroup] = useState("");
  const [editingItemId, setEditingItemId] = useState("");
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [view, setView] = useState<"flow" | "tree">("flow");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const loadSequence = useRef(0);
  const activeProject = useRef(project);

  const load = async (path = project): Promise<void> => {
    const sequence = ++loadSequence.current;
    if (!path.trim()) {
      setNodes([]);
      setConversations([]);
      setRuns([]);
      setTasks([]);
      setWorkbenchItems([]);
      setNotes([]);
      setTodos([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [nextNodes, allConversations, allRuns, allTasks, items, allNotes, allTodos] = await Promise.all([
        fetchProjectNodes(path.trim()),
        fetchConversations(),
        fetchRuns(100),
        fetchTasks(100),
        fetchWorkbenchItems(),
        fetchWorkbenchNotes(500),
        fetchWorkbenchTodos(500),
      ]);
      if (sequence !== loadSequence.current) return;
      setNodes(nextNodes);
      setConversations(allConversations.filter((item) => item.project === path.trim()));
      setRuns(allRuns.filter((item) => item.project === path.trim()));
      setTasks(allTasks.filter((item) => item.project === path.trim()));
      setWorkbenchItems(items);
      setNotes(allNotes.filter((item) => item.project_path === path.trim()));
      setTodos(allTodos.filter((item) => item.project_path === path.trim()));
      setStatus("");
    } catch (error) {
      if (sequence !== loadSequence.current) return;
      setNodes([]);
      setConversations([]);
      setRuns([]);
      setTasks([]);
      setWorkbenchItems([]);
      setNotes([]);
      setTodos([]);
      setStatus(error instanceof Error ? error.message : "项目节点加载失败");
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  };

  const refreshIfCurrent = async (path: string): Promise<void> => {
    if (activeProject.current === path) await load(path);
  };

  useEffect(() => {
    if (project) void load(project);
  }, []);

  useEffect(() => {
    const next = defaultProject?.trim();
    if (project || !next) return;
    setProject(next);
    setDraftPath(next);
    activeProject.current = next;
    localStorage.setItem(PROJECT_PATH_KEY, next);
    window.dispatchEvent(new CustomEvent("qiling-project-changed", { detail: { path: next } }));
    void load(next);
  }, [defaultProject, project]);

  useEffect(() => {
    void fetchAgents().then((result) => { setAgents(result.items); setDefaultExecutor(result.default_executor); }).catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    if (!runs.some((run) => ["queued", "running", "awaiting_approval"].includes(run.status))) return;
    const pollingProject = project;
    const timer = window.setInterval(() => {
      if (activeProject.current !== pollingProject) return;
      void Promise.all(tasks.map(async (task) => [task.task_id, await fetchTaskRun(task.task_id)] as const)).then((results) => {
        if (activeProject.current !== pollingProject) return;
        const latest = new Map(results.filter((entry): entry is readonly [string, AgentRun] => Boolean(entry[1])));
        setRuns((current) => [
          ...current.filter((run) => !latest.has(run.task_id)),
          ...latest.values(),
        ]);
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [runs, tasks]);

  const selectProject = (): void => {
    const next = draftPath.trim();
    if (!next) return;
    setProject(next);
    activeProject.current = next;
    setEditingNoteId(""); setNoteTitle(""); setNoteContent("");
    setEditingItemId(""); setItemTitle(""); setItemUrl(""); setItemGroup("");
    localStorage.setItem(PROJECT_PATH_KEY, next);
    localStorage.setItem(LEGACY_PROJECT_PATH_KEYS[0], next);
    window.dispatchEvent(new CustomEvent("qiling-project-changed", { detail: { path: next } }));
    void load(next);
  };

  const saveNode = async (): Promise<void> => {
    if (!project || !draft.title.trim()) return;
    const payload = {
      project,
      title: draft.title.trim(),
      kind: draft.kind,
      status: draft.status,
      parent_id: draft.parent_id || null,
      next_step: draft.next_step.trim() || null,
      task_ids: draft.task_ids,
    };
    try {
      if (editingId) await updateProjectNode(editingId, payload);
      else await createProjectNode(payload);
      setDraft(EMPTY_DRAFT);
      setEditingId("");
      if (activeProject.current !== project) return;
      await load(project);
      setStatus(editingId ? "节点已更新" : "节点已添加");
    } catch (error) {
      if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "节点保存失败");
    }
  };

  const removeNode = async (node: ProjectNode): Promise<void> => {
    if (!window.confirm(`删除节点「${node.title}」？`)) return;
    try {
      await deleteProjectNode(node.node_id);
      if (editingId === node.node_id) {
        setDraft(EMPTY_DRAFT);
        setEditingId("");
      }
      if (activeProject.current !== project) return;
      await load(project);
      setStatus("节点已删除");
    } catch (error) {
      if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "节点删除失败");
    }
  };

  const startEdit = (node: ProjectNode): void => {
    setEditingId(node.node_id);
    setDraft({
      title: node.title,
      kind: node.kind,
      status: node.status,
      parent_id: node.parent_id ?? "",
      next_step: node.next_step ?? "",
      task_ids: [...node.task_ids],
    });
    setTab("nodes");
    setStatus("");
  };

  const toggleTaskLink = (taskId: string): void => {
    setDraft((prev) => ({
      ...prev,
      task_ids: prev.task_ids.includes(taskId)
        ? prev.task_ids.filter((id) => id !== taskId)
        : [...prev.task_ids, taskId],
    }));
  };

  const addNote = async (): Promise<void> => {
    if (!project || !noteTitle.trim()) return;
    const wasEditing = Boolean(editingNoteId);
    try {
      const payload = { title: noteTitle.trim(), content: noteContent.trim(), project_path: project };
      if (editingNoteId) await updateWorkbenchNote(editingNoteId, payload);
      else await createWorkbenchNote(payload);
      if (activeProject.current !== project) return;
      setNoteTitle("");
      setNoteContent("");
      setEditingNoteId("");
      await load(project);
      setStatus(wasEditing ? "便签已更新" : "便签已添加");
    } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "便签保存失败"); }
  };

  const editNote = (note: WorkbenchNote): void => {
    setEditingNoteId(note.note_id);
    setNoteTitle(note.title);
    setNoteContent(note.content);
  };

  const saveWorkbenchItem = async (): Promise<void> => {
    if (!itemTitle.trim() || !itemUrl.trim()) return;
    const wasEditing = Boolean(editingItemId);
    try {
      const payload = { kind: "link" as const, title: itemTitle.trim(), group: itemGroup.trim() || null, url: itemUrl.trim(), feature_id: null };
      if (editingItemId) await updateWorkbenchItem(editingItemId, payload);
      else await createWorkbenchItem({ id: `link_${crypto.randomUUID().replaceAll("-", "")}`, ...payload, visible: true, order: workbenchItems.length });
      if (activeProject.current !== project) return;
      setItemTitle(""); setItemUrl(""); setItemGroup(""); setEditingItemId("");
      await load(project);
      setStatus(wasEditing ? "入口已更新" : "入口已添加");
    } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "入口保存失败"); }
  };

  const editWorkbenchItem = (item: WorkbenchItem): void => {
    if (item.kind !== "link" || !item.url) return;
    setEditingItemId(item.id); setItemTitle(item.title); setItemUrl(item.url); setItemGroup(item.group ?? "");
  };

  const addTodo = async (): Promise<void> => {
    if (!project || !todoTitle.trim()) return;
    try {
      await createWorkbenchTodo({ title: todoTitle.trim(), description: "", project_path: project });
      if (activeProject.current !== project) return;
      setTodoTitle("");
      await load(project);
      setStatus("待办已添加");
    } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "待办添加失败"); }
  };

  const submitProjectTask = async (): Promise<void> => {
    if (!project || !taskInput.trim()) return;
    try {
      const submittedProject = project;
      await routeTask(taskInput.trim(), null, submittedProject);
      if (activeProject.current !== submittedProject) return;
      setTaskInput("");
      await load(submittedProject);
      setStatus("项目任务已创建");
    } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "项目任务创建失败"); }
  };

  const runTask = async (task: (typeof tasks)[number]): Promise<void> => {
    if (busyRunTask) return;
    const path = project;
    const executor = task.preferred_executor || defaultExecutor || null;
    try {
      setBusyRunTask(task.task_id);
      const result = await executeTask(task.task_id, { executor, mode: runModes[task.task_id] ?? "read-only" });
      if (activeProject.current !== path) return;
      setRuns((current) => [...current.filter((run) => run.task_id !== task.task_id), result.run]);
      setStatus(`任务已交给 ${result.run.executor}`);
    } catch (error) { if (activeProject.current === path) setStatus(error instanceof Error ? error.message : "任务启动失败"); }
    finally { setBusyRunTask(""); }
  };

  const controlRun = async (taskId: string, action: "cancel" | "approved" | "rejected"): Promise<void> => {
    const run = runs.find((item) => item.task_id === taskId);
    if (!run || busyRunTask) return;
    const path = project;
    try {
      setBusyRunTask(taskId);
      const updated = action === "cancel" ? await cancelRun(run.run_id) : await decideRun(run.run_id, action);
      if (activeProject.current !== path) return;
      setRuns((current) => [...current.filter((item) => item.task_id !== taskId), updated]);
      setStatus(action === "cancel" ? "已取消运行" : action === "approved" ? "已批准运行请求" : "已拒绝运行请求");
    } catch (error) { if (activeProject.current === path) setStatus(error instanceof Error ? error.message : "运行操作失败"); }
    finally { setBusyRunTask(""); }
  };

  const projectName = project.split(/[\\/]/).filter(Boolean).pop() || project;
  const artifacts = Array.from(
    new Set([...nodes.flatMap((node) => node.artifact_paths), ...runs.flatMap((run) => run.artifacts)]),
  );
  const completedCount = nodes.filter((node) => node.status === "completed").length;
  const blockedCount = nodes.filter((node) => node.status === "blocked" || node.kind === "blocker").length;
  const activeRuns = runs.filter((run) => run.status === "running" || run.status === "awaiting_approval");
  const tabs: { key: WorkspaceTab; label: string }[] = [
    { key: "overview", label: "概览" },
    { key: "conversations", label: "对话" },
    { key: "nodes", label: "节点" },
    { key: "tasks", label: "任务" },
    { key: "files", label: "文件" },
  ];

  return (
    <section className="flex flex-col gap-3.5">
      <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <label className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="text-xs font-medium text-muted">项目目录</span>
            <input
              className="w-full rounded-lg border border-line px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand/20"
              value={draftPath}
              onChange={(event) => setDraftPath(event.target.value)}
              placeholder="/Users/.../your-project"
              onKeyDown={(event) => { if (event.key === "Enter") selectProject(); }}
            />
          </label>
          <button className="h-10 rounded-lg bg-brand px-4 text-sm font-medium text-onbrand hover:bg-brand-600 disabled:opacity-50" onClick={selectProject} disabled={!draftPath.trim()}>
            打开项目
          </button>
        </div>
        {project && (
          <>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-ink">{projectName}</span>
              <span className="text-[11px] text-muted">项目工作区</span>
              {onOpenChat && (
                <button className="text-xs text-brand hover:underline" onClick={onOpenChat}>
                  打开项目对话
                </button>
              )}
            </div>
            <p className="mt-1 truncate text-[11px] text-muted" title={project}>{project}</p>
            <div className="mt-3 flex flex-wrap gap-1 border-t border-line-subtle pt-3">
              {tabs.map((item) => (
                <button
                  key={item.key}
                  className={`rounded-md px-3 py-1.5 text-xs ${tab === item.key ? "bg-brand-100 font-semibold text-brand" : "text-muted hover:bg-surface-secondary hover:text-ink"}`}
                  onClick={() => setTab(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {status && <p role="status" className={`text-xs ${status.includes("失败") || status.includes("HTTP") ? "text-bad" : "text-muted"}`}>{status}</p>}

      {!project && (
        <section className="rounded-lg border border-dashed border-line bg-surface px-4 py-12 text-center shadow-card">
          <h2 className="text-sm font-semibold text-ink">还没有打开项目</h2>
          <p className="mt-1 text-xs text-muted">输入项目目录后，这里会集中显示项目对话、节点、任务和产物。</p>
        </section>
      )}

      {tab === "overview" && project && (
        <section className="flex flex-col gap-3.5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["节点", nodes.length],
              ["对话", conversations.length],
              ["任务", tasks.length],
              ["进行中", activeRuns.length],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line bg-surface p-4 shadow-card">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
              </div>
            ))}
          </div>
          <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-ink">当前进度</h2>
              <span className="text-xs text-muted">
                {completedCount}/{nodes.length} 已完成
                {blockedCount > 0 && <b className="ml-2 text-bad">{blockedCount} 项阻塞</b>}
              </span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className={`h-full rounded-full transition-all ${blockedCount > 0 ? "bg-warn" : "bg-ok"}`}
                style={{ width: `${nodes.length === 0 ? 0 : Math.round((completedCount / nodes.length) * 100)}%` }}
              />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {[
                { key: "in_progress", label: "进行中", items: nodes.filter((node) => node.status === "in_progress") },
                { key: "blocked", label: "阻塞", items: nodes.filter((node) => node.status === "blocked" || node.kind === "blocker") },
                { key: "next_step", label: "下一步", items: nodes.filter((node) => node.kind === "next_step") },
              ].map(({ key, label, items }) => {
                return (
                  <div key={key} className="rounded-lg bg-surface-secondary px-3 py-3">
                    <div className="text-xs font-medium text-muted">{label}</div>
                    <div className="mt-2 text-sm text-ink">{items[0]?.title || "暂无"}</div>
                  </div>
                );
              })}
            </div>
          </section>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
              <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold text-ink">项目待办</h2><span className="text-xs text-muted">{todos.filter((item) => item.status === "pending").length} 未完成</span></div>
              <form className="mt-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); void addTodo(); }}>
                <input className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-sm" value={todoTitle} onChange={(event) => setTodoTitle(event.target.value)} placeholder="添加项目待办" aria-label="添加项目待办" />
                <button className="rounded-md bg-brand px-3 text-sm font-medium text-onbrand disabled:opacity-50" disabled={!todoTitle.trim()}>添加</button>
              </form>
              <ul className="mt-2 divide-y divide-line-subtle">
                {todos.length === 0 && <li className="py-3 text-xs text-muted">暂无项目待办</li>}
                {todos.map((item) => <li key={item.todo_id} className="flex items-center gap-2 py-2">
                  <input type="checkbox" checked={item.status === "completed"} aria-label={`完成：${item.title}`} onChange={async () => { try { await updateWorkbenchTodo(item.todo_id, { status: item.status === "completed" ? "pending" : "completed" }); await refreshIfCurrent(project); } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "待办更新失败"); } }} />
                  <span className={`min-w-0 flex-1 break-words text-sm ${item.status === "completed" ? "text-muted line-through" : "text-ink"}`}>{item.title}</span>
                  <button className="text-xs text-muted hover:text-bad" aria-label={`删除：${item.title}`} onClick={async () => { try { await deleteWorkbenchTodo(item.todo_id); await refreshIfCurrent(project); } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "待办删除失败"); } }}>删除</button>
                </li>)}
              </ul>
            </section>
            <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
              <h2 className="text-sm font-semibold text-ink">项目便签</h2>
              <form className="mt-3 flex flex-col gap-2" onSubmit={(event) => { event.preventDefault(); void addNote(); }}>
                <input className="min-w-0 rounded-md border border-line px-3 py-2 text-sm" value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="便签标题" aria-label="项目便签标题" />
                <textarea className="min-h-16 resize-y rounded-md border border-line px-3 py-2 text-sm" value={noteContent} onChange={(event) => setNoteContent(event.target.value)} placeholder="记录项目要点" aria-label="项目便签内容" />
                <div className="flex gap-2"><button className="rounded-md border border-line px-3 py-2 text-sm text-ink disabled:opacity-50" disabled={!noteTitle.trim()}>{editingNoteId ? "保存便签" : "添加便签"}</button>{editingNoteId && <button type="button" className="px-2 text-sm text-muted" onClick={() => { setEditingNoteId(""); setNoteTitle(""); setNoteContent(""); }}>取消</button>}</div>
              </form>
              <ul className="mt-2 divide-y divide-line-subtle">
                {notes.length === 0 && <li className="py-3 text-xs text-muted">暂无项目便签</li>}
                {notes.map((item) => <li key={item.note_id} className="flex items-start gap-2 py-2"><div className="min-w-0 flex-1"><div className="break-words text-sm font-medium text-ink">{item.title}</div>{item.content && <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-muted">{item.content}</p>}</div><button className="text-xs text-brand" aria-label={`编辑：${item.title}`} onClick={() => editNote(item)}>编辑</button><button className="text-xs text-muted hover:text-bad" aria-label={`删除：${item.title}`} onClick={async () => { try { await deleteWorkbenchNote(item.note_id); if (activeProject.current !== project) return; if (editingNoteId === item.note_id) { setEditingNoteId(""); setNoteTitle(""); setNoteContent(""); } await load(project); } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "便签删除失败"); } }}>删除</button></li>)}
              </ul>
            </section>
          </div>
          <section className="border-t border-line-subtle pt-3">
            <h2 className="text-sm font-semibold text-ink">工作台入口</h2>
            <form className="mt-2 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void saveWorkbenchItem(); }}>
              <input className="min-w-32 flex-1 rounded-md border border-line px-3 py-2 text-sm" value={itemTitle} onChange={(event) => setItemTitle(event.target.value)} placeholder="入口名称" aria-label="入口名称" />
              <input className="min-w-48 flex-[2] rounded-md border border-line px-3 py-2 text-sm" value={itemUrl} onChange={(event) => setItemUrl(event.target.value)} placeholder="https://example.com" aria-label="入口网址" type="url" />
              <input className="min-w-28 flex-1 rounded-md border border-line px-3 py-2 text-sm" value={itemGroup} onChange={(event) => setItemGroup(event.target.value)} placeholder="分组（可选）" aria-label="入口分组" />
              <button className="rounded-md border border-line px-3 py-2 text-sm disabled:opacity-50" disabled={!itemTitle.trim() || !itemUrl.trim()}>{editingItemId ? "保存入口" : "添加入口"}</button>
              {editingItemId && <button type="button" className="px-2 text-sm text-muted" onClick={() => { setEditingItemId(""); setItemTitle(""); setItemUrl(""); setItemGroup(""); }}>取消</button>}
            </form>
            <ul className="mt-2 divide-y divide-line-subtle">
              {workbenchItems.length === 0 && <li className="py-2 text-xs text-muted">暂无工作台入口</li>}
              {workbenchItems.map((item) => <li key={item.id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="min-w-0 flex-1 text-sm text-ink">{item.title}{item.group && <span className="ml-2 text-xs text-muted">{item.group}</span>}</span>
                {item.url && item.visible && <a className="text-xs text-brand" href={item.url} target="_blank" rel="noreferrer">打开</a>}
                <button className="text-xs text-muted" aria-label={item.visible ? `隐藏：${item.title}` : `显示：${item.title}`} onClick={async () => { try { await updateWorkbenchItem(item.id, { visible: !item.visible }); await refreshIfCurrent(project); } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "入口更新失败"); } }}>{item.visible ? "隐藏" : "显示"}</button>
                {item.kind === "link" && <button className="text-xs text-brand" onClick={() => editWorkbenchItem(item)}>编辑</button>}
                <button className="text-xs text-bad" aria-label={`删除入口：${item.title}`} onClick={async () => { if (!window.confirm(`删除入口「${item.title}」？`)) return; try { await deleteWorkbenchItem(item.id); await refreshIfCurrent(project); } catch (error) { if (activeProject.current === project) setStatus(error instanceof Error ? error.message : "入口删除失败"); } }}>删除</button>
              </li>)}
            </ul>
          </section>
        </section>
      )}

      {tab === "conversations" && project && (
        <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">项目对话</h2>
            {onOpenChat && <button className="text-xs text-brand hover:underline" onClick={onOpenChat}>进入对话</button>}
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {conversations.length === 0 ? <p className="text-sm text-muted">暂无项目对话。</p> : conversations.map((item) => (
              <div key={item.conversation_id} className="rounded-lg border border-line px-3 py-2">
                <div className="text-sm text-ink">{item.title || "新对话"}</div>
                <div className="mt-1 text-[11px] text-muted">{item.message_count} 条消息 · {item.updated_at}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "tasks" && project && (
        <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
          <h2 className="text-sm font-semibold text-ink">项目任务</h2>
          <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); void submitProjectTask(); }}>
            <input className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-sm" value={taskInput} onChange={(event) => setTaskInput(event.target.value)} placeholder="描述要在此项目中完成的工作" aria-label="项目任务描述" />
            <button className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-onbrand disabled:opacity-50" disabled={!taskInput.trim()}>创建任务</button>
          </form>
          <div className="mt-3 flex flex-col gap-2">
            {tasks.length === 0 ? <p className="text-sm text-muted">暂无项目任务。</p> : tasks.map((task) => {
              const run = runs.find((item) => item.task_id === task.task_id);
              const executorName = task.preferred_executor || defaultExecutor;
              const executor = agents.find((item) => item.name === executorName);
              const canRun = ["delegate_backend", "request_approval"].includes(task.category)
                && !["running", "completed", "cancelled"].includes(task.status)
                && (!run || !["queued", "running", "awaiting_approval"].includes(run.status));
              const runActive = Boolean(run && ["queued", "running", "awaiting_approval"].includes(run.status));
              return (
                <div key={task.task_id} className="rounded-md border border-line px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${task.status === "completed" ? "bg-ok" : task.status === "failed" ? "bg-bad" : "bg-brand"}`} />
                    <span className="min-w-0 flex-1 break-words text-sm text-ink">{task.input}</span>
                    <span className="text-[11px] text-muted">{task.status}</span>
                    {run && <span className={`rounded-full px-2 py-0.5 text-[11px] ${run.status === "failed" ? "bg-bad-50 text-bad" : run.status === "completed" ? "bg-ok-50 text-ok" : run.status === "awaiting_approval" ? "bg-warn-50 text-warn" : "bg-brand-50 text-brand"}`}>{run.status} · {run.executor}</span>}
                  </div>
                  {run?.progress && <p className="mt-1 break-words text-xs text-muted">{run.progress}</p>}
                  {run?.error && <p className="mt-1 break-words text-xs text-bad">{run.error}</p>}
                  {run?.result && !runActive && <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted">{run.result}</p>}
                  {run && (run.artifacts.length > 0 || run.checks.length > 0 || run.blockers.length > 0 || run.next_steps.length > 0) && (
                    <dl className="mt-2 grid gap-2 border-t border-line-subtle pt-2 sm:grid-cols-2">
                      {[
                        ["产物", run.artifacts],
                        ["检查", run.checks],
                        ["阻塞", run.blockers],
                        ["下一步", run.next_steps],
                      ].filter(([, values]) => values.length > 0).map(([label, values]) => (
                        <div key={label as string} className="min-w-0">
                          <dt className="text-[11px] font-medium text-muted">{label}</dt>
                          <dd><ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-ink">{(values as string[]).map((value, index) => <li key={`${index}-${value}`} className="break-words">{value}</li>)}</ul></dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {canRun && executor?.available && executor.integration_status === "ready" && <>
                      <select className="rounded-md border border-line px-2 py-1 text-xs" aria-label="项目任务执行模式" value={runModes[task.task_id] ?? "read-only"} onChange={(event) => setRunModes((current) => ({ ...current, [task.task_id]: event.target.value as AgentRunMode }))}>
                        <option value="read-only">只读</option><option value="agent">Agent</option><option value="agent-full-access">完整授权</option>
                      </select>
                      <button className="rounded-md border border-line px-2 py-1 text-xs text-brand disabled:opacity-50" disabled={Boolean(busyRunTask)} onClick={() => void runTask(task)}>{busyRunTask === task.task_id ? "提交中…" : run?.status === "failed" ? "重试" : "运行"}</button>
                    </>}
                    {canRun && executor?.integration_status === "auth_required" && <span className="text-xs text-warn">执行器需要登录：请到「我的智能体」完成授权</span>}
                    {runActive && run?.status === "awaiting_approval" && <>
                      <button className="rounded-md border border-ok/30 px-2 py-1 text-xs text-ok disabled:opacity-50" disabled={Boolean(busyRunTask)} onClick={() => void controlRun(task.task_id, "approved")}>批准</button>
                      <button className="rounded-md border border-bad/30 px-2 py-1 text-xs text-bad disabled:opacity-50" disabled={Boolean(busyRunTask)} onClick={() => void controlRun(task.task_id, "rejected")}>拒绝</button>
                    </>}
                    {runActive && <button className="rounded-md border border-line px-2 py-1 text-xs text-muted disabled:opacity-50" disabled={Boolean(busyRunTask)} onClick={() => void controlRun(task.task_id, "cancel")}>取消运行</button>}
                    {canRun && !executor?.available && executor?.integration_status !== "auth_required" && <span className="text-xs text-muted">执行器不可用</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {tab === "files" && project && (
        <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
          <h2 className="text-sm font-semibold text-ink">项目产物</h2>
          <div className="mt-3 flex flex-col gap-2">
            {artifacts.length === 0 ? <p className="text-sm text-muted">暂无关联文件。任务完成后可从项目节点关联产物。</p> : artifacts.map((path) => (
              <code key={path} className="rounded-lg bg-surface-secondary px-3 py-2 text-xs text-ink break-all">{path}</code>
            ))}
          </div>
        </section>
      )}

      {tab === "nodes" && (
      <section className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 rounded-lg border border-line bg-surface p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-ink">项目进度</h2>
              <p className="mt-0.5 text-xs text-muted">{nodes.length} 个节点 · {view === "flow" ? "阶段与依赖主视图" : "项目拆解辅助视图"}</p>
            </div>
            <div className="flex items-center gap-3">
              <button className={`text-xs ${view === "flow" ? "font-semibold text-brand" : "text-muted hover:text-ink"}`} onClick={() => setView("flow")}>流程图</button>
              <button className={`text-xs ${view === "tree" ? "font-semibold text-brand" : "text-muted hover:text-ink"}`} onClick={() => setView("tree")}>树状图</button>
              <button className="text-xs text-brand hover:underline" onClick={() => void load()} disabled={loading}>{loading ? "加载中…" : "刷新"}</button>
            </div>
          </div>
          {view === "flow" ? (
            <FlowView nodes={nodes} onEdit={startEdit} onDelete={(node) => void removeNode(node)} />
          ) : (
            <TreeView nodes={nodes} onEdit={startEdit} onDelete={(node) => void removeNode(node)} />
          )}
        </section>

        <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-ink">{editingId ? "编辑节点" : "新增节点"}</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                {editingId ? "修改后保存，状态流转会同步到流程图。" : "流程图和树状图共用同一份节点数据。"}
              </p>
            </div>
            {editingId && (
              <button className="shrink-0 text-xs text-muted hover:text-ink" onClick={() => { setDraft(EMPTY_DRAFT); setEditingId(""); }} type="button">
                取消
              </button>
            )}
          </div>
          <div className="mt-3 flex flex-col gap-2.5">
            <input className="rounded-lg border border-line px-3 py-2 text-sm" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="节点名称" />
            <select className="rounded-lg border border-line px-3 py-2 text-sm" value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as ProjectNodeKind })}>
              {Object.entries(KIND_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select className="rounded-lg border border-line px-3 py-2 text-sm" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ProjectNodeStatus })}>
              {Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select className="rounded-lg border border-line px-3 py-2 text-sm" value={draft.parent_id} onChange={(event) => setDraft({ ...draft, parent_id: event.target.value })}>
              <option value="">无父节点</option>
              {nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.title}</option>)}
            </select>
            <input className="rounded-lg border border-line px-3 py-2 text-sm" value={draft.next_step} onChange={(event) => setDraft({ ...draft, next_step: event.target.value })} placeholder="下一步（可选）" />
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted">关联任务（完成后自动推进节点状态）</span>
              {tasks.length === 0 ? (
                <span className="text-[11px] text-muted">本项目暂无任务。</span>
              ) : (
                <div className="max-h-32 space-y-1 overflow-y-auto rounded-lg border border-line bg-surface-secondary p-2">
                  {tasks.slice(0, 20).map((task) => (
                    <label key={task.task_id} className="flex cursor-pointer items-start gap-2 text-[11px] text-ink">
                      <input
                        className="mt-0.5 shrink-0"
                        type="checkbox"
                        checked={draft.task_ids.includes(task.task_id)}
                        onChange={() => toggleTaskLink(task.task_id)}
                      />
                      <span className="min-w-0 break-words">{task.input}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
            <button className="rounded-lg bg-brand px-3 py-2 text-sm font-medium text-onbrand hover:bg-brand-600 disabled:opacity-50" onClick={() => void saveNode()} disabled={!project || !draft.title.trim()}>
              {editingId ? "保存修改" : "添加节点"}
            </button>
            {editingId && (
              <button
                className="rounded-lg border border-bad/30 px-3 py-2 text-sm font-medium text-bad hover:bg-bad-50"
                onClick={() => {
                  const node = nodes.find((item) => item.node_id === editingId);
                  if (node) void removeNode(node);
                }}
                type="button"
              >
                删除此节点
              </button>
            )}
          </div>
          {status && <p className={`mt-2 text-xs ${status.includes("失败") ? "text-bad" : "text-ok"}`}>{status}</p>}
        </section>
      </section>
      )}
    </section>
  );
}
