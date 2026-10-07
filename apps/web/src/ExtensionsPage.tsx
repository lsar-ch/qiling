import { useCallback, useEffect, useRef, useState } from "react";

import {
  addMcpServer,
  deleteMcpServer,
  deleteSkill,
  fetchMcpServers,
  fetchMcpTools,
  fetchOfficeTools,
  fetchSkill,
  fetchSkills,
  installOfficeTool,
  registerSkillDirectory,
  testMcpServer,
  toggleMcpServer,
  toggleSkill,
  uploadSkillZip,
  type McpServerPayload,
} from "./api";
import type {
  McpServerInfo,
  OfficeToolInfo,
  SkillDetail,
  SkillInfo,
} from "@qiling/contracts";

const CARD_CLS =
  "rounded-lg border border-line bg-surface shadow-card p-4 flex flex-col gap-2.5 min-w-0";

type Tab = "skills" | "mcp" | "tools";

function SourceTag({ source }: { source: SkillInfo["source"] }) {
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded-full ${
        source === "builtin"
          ? "bg-brand-50 text-brand"
          : "bg-surface-tertiary text-muted"
      }`}
    >
      {source === "builtin" ? "内置" : "用户"}
    </span>
  );
}

function SkillDrawer({
  skill,
  onClose,
}: {
  skill: SkillInfo;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError("");
    fetchSkill(skill.id)
      .then((item) => {
        if (!cancelled) setDetail(item);
      })
      .catch((item: unknown) => {
        if (!cancelled) setError(item instanceof Error ? item.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [skill.id]);

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <aside
        className="w-full max-w-md h-full bg-surface p-6 overflow-y-auto"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="text-base font-semibold text-ink">{skill.name}</h3>
            <p className="text-xs text-muted mt-1">{skill.description}</p>
          </div>
          <button
            className="text-sm text-muted px-2 py-1 rounded hover:bg-surface-tertiary"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 mb-5">
          <SourceTag source={skill.source} />
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              skill.enabled ? "bg-ok-50 text-ok" : "bg-surface-tertiary text-muted"
            }`}
          >
            {skill.enabled ? "已启用" : "已停用"}
          </span>
          {skill.has_scripts && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-line-subtle text-muted">
              含脚本
            </span>
          )}
        </div>
        {error && (
          <div className="text-sm text-bad bg-bad-50 rounded-lg px-3 py-2">{error}</div>
        )}
        {!detail && !error && <p className="text-sm text-muted">加载中…</p>}
        {detail && (
          <>
            {detail.triggers.length > 0 && (
              <div className="mb-4">
                <p className="text-[11px] text-muted mb-1.5">触发词</p>
                <div className="flex flex-wrap gap-1.5">
                  {detail.triggers.map((item) => (
                    <span
                      key={item}
                      className="text-[11px] px-2 py-0.5 rounded bg-surface-tertiary text-ink"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <pre className="whitespace-pre-wrap text-sm text-ink leading-relaxed font-sans">
              {detail.body}
            </pre>
          </>
        )}
      </aside>
    </div>
  );
}

function AddSkillDialog({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (skill: SkillInfo) => void;
}) {
  const [mode, setMode] = useState<"zip" | "dir">("zip");
  const [dirPath, setDirPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const submit = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      if (mode === "zip") {
        const file = fileRef.current?.files?.[0];
        if (!file) throw new Error("请先选择技能 zip 包");
        onAdded(await uploadSkillZip(file));
      } else {
        if (!dirPath.trim()) throw new Error("请填写技能目录的绝对路径");
        onAdded(await registerSkillDirectory(dirPath.trim()));
      }
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "添加失败");
      setBusy(false);
    }
  }, [mode, dirPath, onAdded]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-surface rounded-xl p-6 mx-4"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink mb-4">添加技能</h3>
        <div className="flex gap-2 mb-4">
          <button
            className={`flex-1 px-3 py-2 rounded-lg text-sm ${
              mode === "zip" ? "bg-brand-100 text-brand" : "bg-surface-tertiary text-muted"
            }`}
            onClick={() => setMode("zip")}
          >
            上传 zip 包
          </button>
          <button
            className={`flex-1 px-3 py-2 rounded-lg text-sm ${
              mode === "dir" ? "bg-brand-100 text-brand" : "bg-surface-tertiary text-muted"
            }`}
            onClick={() => setMode("dir")}
          >
            本地目录
          </button>
        </div>
        {mode === "zip" ? (
          <input ref={fileRef} type="file" accept=".zip" className="text-sm w-full" />
        ) : (
          <input
            value={dirPath}
            onChange={(event) => setDirPath(event.target.value)}
            placeholder="/Users/you/my-skill（含 SKILL.md 的目录绝对路径）"
            className="w-full text-sm border border-line rounded-lg px-3 py-2"
          />
        )}
        {error && <p className="text-xs text-bad mt-3">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button
            className="px-4 py-2 text-sm rounded-lg text-muted hover:bg-surface-tertiary"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="px-4 py-2 text-sm rounded-lg bg-brand text-onbrand disabled:opacity-60"
            disabled={busy}
            onClick={submit}
          >
            {busy ? "添加中…" : "添加"}
          </button>
        </div>
      </div>
    </div>
  );
}

function McpStatusTag({ server }: { server: McpServerInfo }) {
  const label =
    server.status === "ready"
      ? "就绪"
      : server.status === "error"
        ? "异常"
        : server.status === "disabled"
          ? "已停用"
          : "未启动";
  const cls =
    server.status === "ready"
      ? "bg-ok-50 text-ok"
      : server.status === "error"
        ? "bg-bad-50 text-bad"
        : "bg-surface-tertiary text-muted";
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${cls}`}>{label}</span>
  );
}

function AddMcpDialog({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [id, setId] = useState("");
  const [transport, setTransport] = useState<"stdio" | "streamablehttp">("stdio");
  const [access, setAccess] = useState<"read" | "write">("read");
  const [enabled, setEnabled] = useState(true);
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [envText, setEnvText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (!/^[a-z0-9][a-z0-9_-]{0,40}$/.test(id.trim())) {
        throw new Error("id 只能含小写字母、数字、-、_（≤40 字符）");
      }
      const args = argsText
        .split(/\s+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const env: Record<string, string> = {};
      for (const line of envText.split("\n")) {
        const pair = line.trim();
        if (!pair) continue;
        const idx = pair.indexOf("=");
        if (idx <= 0) throw new Error(`环境变量格式错误：${pair}（应为 KEY=VALUE）`);
        env[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
      }
      const payload: McpServerPayload = {
        id: id.trim(),
        transport,
        access,
        enabled,
        command: transport === "stdio" ? command.trim() : undefined,
        args: transport === "stdio" ? args : undefined,
        env: transport === "stdio" ? env : undefined,
        url: transport === "streamablehttp" ? url.trim() : undefined,
      };
      await addMcpServer(payload);
      onAdded();
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "添加失败");
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-surface rounded-xl p-6 mx-4"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink mb-4">添加 MCP 服务器</h3>
        <div className="flex flex-col gap-3">
          <label className="text-xs text-muted">
            ID
            <input
              className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm"
              value={id}
              onChange={(event) => setId(event.target.value)}
              placeholder="如 obsidian"
            />
          </label>
          <div className="flex gap-4">
            <label className="text-xs text-muted flex items-center gap-1.5">
              <select
                className="rounded-lg border border-line px-2 py-1.5 text-sm text-ink"
                value={transport}
                onChange={(event) => setTransport(event.target.value as "stdio" | "streamablehttp")}
              >
                <option value="stdio">stdio（本地进程）</option>
                <option value="streamablehttp">streamablehttp（远程）</option>
              </select>
            </label>
            <label className="text-xs text-muted flex items-center gap-1.5">
              <select
                className="rounded-lg border border-line px-2 py-1.5 text-sm text-ink"
                value={access}
                onChange={(event) => setAccess(event.target.value as "read" | "write")}
              >
                <option value="read">只读（自动放行）</option>
                <option value="write">读写（需授权）</option>
              </select>
            </label>
            <label className="text-xs text-muted flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              启用
            </label>
          </div>
          {transport === "stdio" ? (
            <>
              <label className="text-xs text-muted">
                Command
                <input
                  className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm"
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  placeholder="绝对路径，如 /usr/local/bin/node"
                />
              </label>
              <label className="text-xs text-muted">
                参数（空格分隔）
                <input
                  className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm"
                  value={argsText}
                  onChange={(event) => setArgsText(event.target.value)}
                  placeholder="/path/to/server.js"
                />
              </label>
              <label className="text-xs text-muted">
                环境变量（每行 KEY=VALUE）
                <textarea
                  className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm"
                  rows={3}
                  value={envText}
                  onChange={(event) => setEnvText(event.target.value)}
                  placeholder="API_KEY=xxx"
                />
              </label>
            </>
          ) : (
            <label className="text-xs text-muted">
              URL
              <input
                className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com/mcp"
              />
            </label>
          )}
          {error && (
            <div className="text-sm text-bad bg-bad-50 rounded-lg px-3 py-2">{error}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              className="text-sm text-muted px-3 py-2 rounded-lg hover:bg-surface-tertiary"
              onClick={onClose}
            >
              取消
            </button>
            <button
              className="text-sm px-3 py-2 rounded-lg bg-brand text-onbrand"
              onClick={() => void submit()}
              disabled={busy}
            >
              {busy ? "添加中…" : "添加"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function McpPanel() {
  const [servers, setServers] = useState<McpServerInfo[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [viewing, setViewing] = useState<{
    server: McpServerInfo;
    tools: { name: string; description: string; input_schema: Record<string, unknown> }[];
  } | null>(null);

  const load = useCallback(() => {
    fetchMcpServers()
      .then(setServers)
      .catch((item: unknown) =>
        setError(item instanceof Error ? item.message : "加载失败"),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onToggle = async (server: McpServerInfo) => {
    try {
      await toggleMcpServer(server.id, !server.enabled);
      load();
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "操作失败");
    }
  };

  const onDelete = async (server: McpServerInfo) => {
    if (!window.confirm(`确认删除 MCP 服务器「${server.id}」？此操作不可恢复。`)) return;
    try {
      await deleteMcpServer(server.id);
      load();
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "删除失败");
    }
  };

  const onTest = async (server: McpServerInfo) => {
    setNotice("");
    setError("");
    try {
      const tools = await testMcpServer(server.id);
      setNotice(`「${server.id}」连接成功，发现 ${tools.length} 个工具`);
      load();
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "连接失败");
      load();
    }
  };

  const onViewTools = async (server: McpServerInfo) => {
    try {
      const tools = await fetchMcpTools(server.id);
      setViewing({ server, tools });
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "读取工具失败");
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          MCP 服务器懒启动：仅在使用工具时拉起进程，空闲后自动回收。
        </p>
        <button
          className="text-sm px-3 py-2 rounded-lg bg-brand text-onbrand shrink-0"
          onClick={() => setShowAdd(true)}
        >
          + 添加服务器
        </button>
      </div>
      {error && (
        <div className="rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm">{error}</div>
      )}
      {notice && (
        <div className="rounded-lg bg-ok-50 text-ok px-4 py-3 text-sm">{notice}</div>
      )}
      {!servers && !error && <p className="text-sm text-muted">加载中…</p>}
      {servers && servers.length === 0 && (
        <div className="rounded-lg border border-dashed border-line bg-surface px-5 py-10 text-center">
          <p className="text-sm text-ink font-medium mb-1.5">还没有 MCP 服务器</p>
          <p className="text-xs text-muted">
            添加本地 stdio 进程或远程 streamablehttp 服务器，为对话接入可调用工具。
          </p>
        </div>
      )}
      {servers && servers.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {servers.map((server) => (
            <div key={server.id} className={CARD_CLS}>
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-ink truncate">{server.id}</h3>
                <McpStatusTag server={server} />
              </div>
              <p className="text-xs text-muted leading-relaxed line-clamp-2">
                {server.transport === "stdio"
                  ? server.command
                  : server.url}
              </p>
              <div className="flex items-center gap-2 text-[10px] text-muted">
                <span>{server.transport}</span>
                <span>·</span>
                <span>{server.access === "read" ? "只读" : "读写"}</span>
                <span>·</span>
                <span>{server.tool_count} 工具</span>
              </div>
              {server.status === "error" && server.detail && (
                <p className="text-[11px] text-bad bg-bad-50 rounded px-2 py-1 line-clamp-2">
                  {server.detail}
                </p>
              )}
              <div className="flex items-center justify-between gap-2 mt-auto pt-1">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={server.enabled}
                    onChange={() => void onToggle(server)}
                  />
                  <span className="text-[10px] text-muted">
                    {server.enabled ? "已启用" : "已停用"}
                  </span>
                </label>
                <div className="flex items-center gap-2">
                  <button
                    className="text-[11px] text-brand"
                    onClick={() => void onTest(server)}
                  >
                    测试
                  </button>
                  <button
                    className="text-[11px] text-brand"
                    onClick={() => void onViewTools(server)}
                  >
                    工具
                  </button>
                  <button
                    className="text-[11px] text-bad"
                    onClick={() => void onDelete(server)}
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {showAdd && (
        <AddMcpDialog
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            setNotice("已添加 MCP 服务器");
            load();
          }}
        />
      )}
      {viewing && (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-black/30"
          onClick={() => setViewing(null)}
        >
          <aside
            className="w-full max-w-md h-full bg-surface p-6 overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 mb-4">
              <h3 className="text-base font-semibold text-ink">{viewing.server.id} 工具</h3>
              <button
                className="text-sm text-muted px-2 py-1 rounded hover:bg-surface-tertiary"
                onClick={() => setViewing(null)}
              >
                关闭
              </button>
            </div>
            {viewing.tools.length === 0 && (
              <p className="text-sm text-muted">该服务器没有暴露工具。</p>
            )}
            <div className="flex flex-col gap-3">
              {viewing.tools.map((tool) => (
                <div
                  key={tool.name}
                  className="rounded-lg border border-line bg-surface p-3"
                >
                  <p className="text-sm font-semibold text-ink">{tool.name}</p>
                  <p className="text-xs text-muted leading-relaxed mt-1">
                    {tool.description || "（无说明）"}
                  </p>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

export default function ExtensionsPage() {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<SkillInfo[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<SkillInfo | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    fetchSkills()
      .then(setSkills)
      .catch((item: unknown) =>
        setError(item instanceof Error ? item.message : "加载失败"),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onToggle = useCallback(
    async (skill: SkillInfo) => {
      try {
        await toggleSkill(skill.id, !skill.enabled);
        load();
      } catch (item: unknown) {
        setError(item instanceof Error ? item.message : "操作失败");
      }
    },
    [load],
  );

  const onDelete = useCallback(
    async (skill: SkillInfo) => {
      if (!window.confirm(`确认删除用户技能「${skill.name}」？此操作不可恢复。`)) return;
      try {
        await deleteSkill(skill.id);
        load();
      } catch (item: unknown) {
        setError(item instanceof Error ? item.message : "删除失败");
      }
    },
    [load],
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 border-b border-line">
          {(
            [
              { key: "skills", label: "智能技能" },
              { key: "mcp", label: "MCP 服务器" },
              { key: "tools", label: "办公工具" },
            ] as { key: Tab; label: string }[]
          ).map((item) => (
            <button
              key={item.key}
              className={`px-4 py-2.5 text-sm border-b-2 -mb-px ${
                tab === item.key
                  ? "border-brand text-brand font-semibold"
                  : "border-transparent text-muted hover:text-ink"
              }`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {tab === "skills" && (
          <button
            className="text-sm px-3 py-2 rounded-lg bg-brand text-onbrand shrink-0"
            onClick={() => setShowAdd(true)}
          >
            + 添加技能
          </button>
        )}
      </div>

      {tab === "skills" && (
        <>
          {error && (
            <div className="rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm">{error}</div>
          )}
          {notice && (
            <div className="rounded-lg bg-ok-50 text-ok px-4 py-3 text-sm">{notice}</div>
          )}
          {!skills && !error && <p className="text-sm text-muted">加载中…</p>}
          {skills && (
            <>
              <p className="text-xs text-muted">
                共 {skills.length} 个技能；内置技能可停用，用户技能可删除。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {skills.map((skill) => (
                  <div key={skill.id} className={`${CARD_CLS}`}>
                    <div className="flex items-center justify-between gap-2">
                      <button
                        className="text-left min-w-0"
                        onClick={() => setSelected(skill)}
                      >
                        <h3 className="text-sm font-semibold text-ink truncate">{skill.name}</h3>
                      </button>
                      <SourceTag source={skill.source} />
                    </div>
                    <button className="text-left" onClick={() => setSelected(skill)}>
                      <p className="text-xs text-muted leading-relaxed line-clamp-3">
                        {skill.description}
                      </p>
                    </button>
                    <div className="flex items-center justify-between gap-2 mt-auto pt-1">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={skill.enabled}
                          onChange={() => onToggle(skill)}
                        />
                        <span className="text-[10px] text-muted">
                          {skill.enabled ? "已启用" : "已停用"}
                        </span>
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          className="text-[11px] text-brand"
                          onClick={() => setSelected(skill)}
                        >
                          查看
                        </button>
                        {skill.source === "user" && (
                          <button
                            className="text-[11px] text-bad"
                            onClick={() => onDelete(skill)}
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {tab === "mcp" && (
        <McpPanel />
      )}

      {tab === "tools" && <OfficeToolsPanel />}

      {selected && (
        <SkillDrawer skill={selected} onClose={() => setSelected(null)} />
      )}
      {showAdd && (
        <AddSkillDialog
          onClose={() => setShowAdd(false)}
          onAdded={(skill) => {
            setShowAdd(false);
            setNotice(`已添加技能「${skill.name}」`);
            load();
          }}
        />
      )}
    </div>
  );
}

const POWER_LABELS: Record<string, string> = {
  word: "Word",
  excel: "表格",
  ppt: "幻灯片",
  pdf: "PDF",
  markdown: "Markdown",
};

/** 办公引擎清单：探测本机是否已装，pip 类型一键安装，link 类型跳下载页。 */
function OfficeToolsPanel() {
  const [tools, setTools] = useState<OfficeToolInfo[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      setTools(await fetchOfficeTools());
      setError("");
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const install = useCallback(async (tool: OfficeToolInfo) => {
    setBusy(tool.name);
    setError("");
    setNotice("");
    try {
      const result = await installOfficeTool(tool.name);
      if (result.tools.length) setTools(result.tools);
      if (result.ok) setNotice(result.message.split("\n")[0]);
      else setError(result.message);
    } catch (item: unknown) {
      setError(item instanceof Error ? item.message : "安装失败");
    } finally {
      setBusy("");
    }
  }, []);

  const readyCount = tools?.filter((tool) => tool.installed).length ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          写作与排版用的外部引擎（Progressive Enhancement）：栖灵只做探测、安装和调用，
          工具本体由各项目自行分发。
        </p>
        <button
          className="text-brand text-xs hover:underline shrink-0"
          onClick={() => void load()}
        >
          重新检测
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-bad-50 text-bad px-4 py-3 text-sm whitespace-pre-wrap break-anywhere">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg bg-ok-50 text-ok px-4 py-3 text-sm">{notice}</div>
      )}
      {!tools && !error && <p className="text-sm text-muted">正在探测本机办公引擎…</p>}
      {tools && (
        <>
          <p className="text-xs text-muted">
            共 {tools.length} 个引擎，已就绪 {readyCount} 个。
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {tools.map((tool) => (
              <div key={tool.name} className={CARD_CLS}>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink min-w-0 break-anywhere">
                    {tool.label}
                  </h3>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${
                      tool.installed
                        ? "bg-ok-50 text-ok"
                        : "bg-surface-tertiary text-muted"
                    }`}
                  >
                    {tool.installed ? "已就绪" : "未安装"}
                  </span>
                </div>
                <p className="text-xs text-muted leading-relaxed">{tool.detail}</p>
                <div className="flex flex-wrap gap-1.5">
                  {tool.powers.map((power) => (
                    <span
                      key={power}
                      className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-tertiary text-muted"
                    >
                      {POWER_LABELS[power] ?? power}
                    </span>
                  ))}
                  {tool.license && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-tertiary text-muted">
                      {tool.license}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-end gap-2 mt-auto pt-1">
                  {!tool.installed && tool.install_kind === "pip" && (
                    <button
                      className="text-[11px] px-2.5 py-1 rounded bg-brand text-onbrand disabled:opacity-50"
                      disabled={Boolean(busy)}
                      onClick={() => void install(tool)}
                    >
                      {busy === tool.name ? "安装中…" : "安装"}
                    </button>
                  )}
                  {!tool.installed && tool.install_kind === "link" && tool.homepage && (
                    <a
                      className="text-[11px] px-2.5 py-1 rounded bg-brand text-onbrand"
                      href={tool.homepage}
                      target="_blank"
                      rel="noreferrer"
                    >
                      去下载
                    </a>
                  )}
                  {tool.installed && tool.homepage && (
                    <a
                      className="text-[11px] text-brand hover:underline"
                      href={tool.homepage}
                      target="_blank"
                      rel="noreferrer"
                    >
                      官网
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
