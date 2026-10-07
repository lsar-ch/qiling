import { useState } from "react";
import {
  MessagesSquare,
  FolderKanban,
  Bell,
  ChevronDown,
  Activity,
  Radio,
  ArrowRight,
} from "lucide-react";
import type {
  AgentInfo,
  EventEnvelope,
} from "@qiling/contracts";
import type {
  HealthResponse,
  SessionResponse,
} from "./api";
import { stateLabelForHome } from "./home-helpers";

type HomePageProps = {
  current: string;
  widgetMessage?: string;
  wsOpen: boolean;
  serviceOk: boolean;
  serviceLost: boolean;
  health: HealthResponse | null;
  agents: AgentInfo[];
  session: SessionResponse | null;
  events: EventEnvelope[];
  runDemo(action: { eventType: string }): Promise<void>;
  runSequence(): Promise<void>;
  demoMsg: string;
  onNavigate(key: string): void;
};

const DEMO_BUTTONS = [
  { label: "聆听", eventType: "speech.started" },
  { label: "思考", eventType: "conversation.input" },
  { label: "说话", eventType: "conversation.response" },
  { label: "执行", eventType: "task.started" },
  { label: "等待授权", eventType: "task.approval_required" },
  { label: "完成", eventType: "task.completed" },
  { label: "打断", eventType: "speech.interrupted" },
];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "夜深了";
  if (h < 11) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}

const QUICK = [
  { label: "项目", icon: FolderKanban, target: "project" },
  { label: "提醒", icon: Bell, target: "reminders" },
];

export default function HomePage({
  current,
  widgetMessage,
  wsOpen,
  serviceOk,
  health,
  agents,
  events,
  runDemo,
  runSequence,
  demoMsg,
  onNavigate,
}: HomePageProps) {
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const readyAgents = agents.filter((a) => a.integration_status === "ready").length;
  const stateText = stateLabelForHome(current);
  const detailText =
    widgetMessage && widgetMessage !== stateText ? widgetMessage : "随时待命";

  const statusChips = [
    { label: "本地服务", ok: serviceOk, on: "运行中", off: "离线" },
    { label: "语音识别", ok: health?.voice_pipeline?.stt_ready, on: "就绪", off: "不可用" },
    { label: "语音合成", ok: health?.voice_pipeline?.tts_ready, on: "就绪", off: "不可用" },
    { label: "执行器", ok: readyAgents > 0, on: `${readyAgents} 个可用`, off: "无可用" },
  ];

  return (
    <div className="flex flex-col gap-6 animate-fade-up">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-xl border border-line bg-surface shadow-card">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-16 w-[420px] h-[420px] rounded-full bg-accent/[0.07]" />
          <div className="absolute -bottom-32 -left-10 w-[360px] h-[360px] rounded-full bg-brand/[0.08]" />
        </div>
        <div className="relative flex items-center gap-6 px-7 py-8 md:px-9 md:py-10">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-3">
              <span className="relative flex w-2.5 h-2.5">
                <span
                  className={`absolute inline-flex w-full h-full rounded-full ${
                    current === "listening" ? "bg-brand animate-pulse-ring" : "bg-accent"
                  }`}
                />
                <span
                  className={`relative inline-flex w-2.5 h-2.5 rounded-full ${
                    current === "listening" ? "bg-brand" : "bg-accent"
                  }`}
                />
              </span>
              <span className="text-xs font-medium text-muted">
                {stateText} · {detailText}
              </span>
            </div>
            <h2 className="text-[32px] md:text-[38px] font-bold text-ink tracking-tightish leading-tight mb-3">
              {greeting()}，有什么要一起忙的？
            </h2>
            <p className="text-sm text-muted leading-relaxed max-w-md mb-6">
              我记得住项目上下文，能语音对话，也会把复杂任务交给执行器。数据都在这台设备上。
            </p>
            <div className="flex flex-wrap items-center gap-2.5">
              <button
                type="button"
                onClick={() => onNavigate("chat")}
                className="inline-flex items-center gap-2 rounded-md bg-ink py-2.5 px-5 text-sm font-medium text-surface hover:bg-ink/88 transition-all duration-200 ease-expo cursor-pointer"
              >
                <MessagesSquare size={16} strokeWidth={2} />
                开始对话
                <ArrowRight size={15} strokeWidth={2} />
              </button>
              {QUICK.map((q) => {
                const Icon = q.icon;
                return (
                  <button
                    key={q.target}
                    type="button"
                    onClick={() => onNavigate(q.target)}
                    className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-medium text-ink hover:border-ink/30 hover:bg-surface-tertiary transition-all duration-200 ease-expo cursor-pointer"
                  >
                    <Icon size={15} strokeWidth={1.8} className="text-muted" />
                    {q.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="hidden md:block shrink-0 w-52 lg:w-60 self-end">
            <img
              src="/persona-default.png"
              alt=""
              className="w-full h-auto object-contain drop-shadow-[0_12px_24px_rgba(60,50,35,0.18)]"
            />
          </div>
        </div>
      </section>

      {/* Compact status */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statusChips.map((chip) => {
          const ok = chip.ok;
          return (
            <div
              key={chip.label}
              className="rounded-lg border border-line bg-surface px-4 py-3.5 shadow-card"
            >
              <div className="text-xs text-muted mb-1.5">{chip.label}</div>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    ok === undefined ? "bg-muted" : ok ? "bg-ok" : "bg-bad"
                  }`}
                />
                <span className="text-sm font-semibold text-ink">
                  {ok === undefined ? "—" : ok ? chip.on : chip.off}
                </span>
              </div>
            </div>
          );
        })}
      </section>

      {/* Executor badges + connection */}
      <section className="rounded-lg border border-line bg-surface shadow-card">
        <div className="px-5 py-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink">执行器</h3>
          <button
            type="button"
            onClick={() => onNavigate("agents")}
            className="text-xs font-medium text-brand hover:underline"
          >
            管理 →
          </button>
        </div>
        <div className="px-5 pb-4 flex flex-wrap gap-2">
          {agents.map((agent) => {
            const ready = agent.integration_status === "ready";
            return (
              <span
                key={agent.name}
                title={agent.version ? `v${agent.version}` : agent.integration_status}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs border ${
                  ready
                    ? "bg-ok-50 border-ok/20 text-ink"
                    : "bg-surface-secondary border-line text-muted"
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${ready ? "bg-ok" : "bg-muted"}`} />
                {agent.label}
              </span>
            );
          })}
        </div>
        <div className="border-t border-line px-5 py-2.5 flex items-center gap-2 bg-surface-tertiary">
          <Radio size={13} className={wsOpen ? "text-ok" : "text-muted"} />
          <span className="text-[11px] text-muted">
            事件通道 {wsOpen ? "已连接" : "未连接"}
          </span>
        </div>
      </section>

      {/* Diagnostics (collapsed) */}
      <section className="rounded-lg border border-line bg-surface">
        <button
          type="button"
          onClick={() => setShowDiagnostics((v) => !v)}
          className="w-full flex items-center justify-between px-5 py-3.5 cursor-pointer"
        >
          <span className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Activity size={15} className="text-muted" />
            诊断与状态演练
          </span>
          <ChevronDown
            size={16}
            className={`text-muted transition-transform duration-200 ease-expo ${
              showDiagnostics ? "rotate-180" : ""
            }`}
          />
        </button>
        {showDiagnostics && (
          <div className="border-t border-line px-5 py-4 space-y-5 animate-fade-up">
            <div>
              <div className="text-xs font-semibold text-ink mb-2.5">状态演练</div>
              <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2">
                {DEMO_BUTTONS.map((b) => (
                  <button
                    key={b.eventType}
                    type="button"
                    onClick={() => void runDemo(b)}
                    className="px-2 py-2 text-xs font-medium rounded-md border border-line bg-surface-tertiary text-ink hover:border-brand hover:text-brand transition-colors cursor-pointer"
                  >
                    {b.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3 mt-3">
                <button
                  type="button"
                  onClick={() => void runSequence()}
                  className="px-4 py-2 text-xs font-medium rounded-md bg-brand text-onbrand hover:bg-brand-600 transition-colors cursor-pointer"
                >
                  演示完整流程
                </button>
                {demoMsg && <span className="text-xs text-ok">{demoMsg}</span>}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-ink mb-2.5">最近事件</div>
              {events.length === 0 ? (
                <p className="text-xs text-muted">暂无事件。</p>
              ) : (
                <div className="space-y-1.5 max-h-44 overflow-y-auto scroll-thin">
                  {[...events].reverse().map((ev, i) => (
                    <div
                      key={`${ev.event_id}-${i}`}
                      className="flex items-center justify-between px-3 py-1.5 rounded-md bg-surface-secondary"
                    >
                      <span className="text-[11px] font-semibold text-brand font-mono">
                        {ev.event_type}
                      </span>
                      <span className="text-[11px] text-muted">{ev.task_id ?? ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
