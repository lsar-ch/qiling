import { useEffect, useState, type ReactNode } from "react";
import { fetchHealth, type HealthResponse } from "./api";

const CARD_CLS =
  "rounded-lg border border-line bg-white shadow-card p-4 flex flex-col gap-3 min-w-0";
const TITLE_CLS = "text-sm font-semibold text-ink";
const BODY_CLS = "text-xs text-muted leading-relaxed";

const PERF_ZH: Record<HealthResponse["performance_mode"], string> = {
  quality: "高质量",
  balanced: "均衡",
  lite: "轻量",
};

const DIRS: { label: string; path: string }[] = [
  { label: "记忆", path: "data/memory" },
  { label: "会话", path: "data/conversations" },
  { label: "任务", path: "data/tasks" },
  { label: "角色卡", path: "config/personas" },
  { label: "运行日志", path: "data/run_logs" },
];

const STACK: string[] = [
  "Codex ACP",
  "FastAPI",
  "React/Vite",
  "Tauri",
  "Tailwind CSS",
];

function fmtUptime(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const days = Math.floor(s / 86400);
  const hh = Math.floor((s % 86400) / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
  return days > 0 ? `${days} 天 ${time}` : time;
}

function InfoRow({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 min-w-0">
      <span className="text-xs text-muted shrink-0">{label}</span>
      <span
        className={`text-sm text-ink font-medium text-right min-w-0 ${
          mono ? "font-mono text-xs" : ""
        }`}
      >
        {children}
      </span>
    </div>
  );
}

function StatusPill({ loaded, ok }: { loaded: boolean; ok: boolean }) {
  if (!loaded) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-line-subtle text-muted">
        <span className="w-1.5 h-1.5 rounded-full bg-muted" />
        检测中
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${
        ok ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad"
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-ok" : "bg-bad"}`} />
      {ok ? "运行中" : "失败"}
    </span>
  );
}

export default function AboutPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchHealth()
      .then((h) => {
        if (alive) setHealth(h);
      })
      .catch(() => {
        /* 服务离线时保持 null，由失败状态呈现 */
      })
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const serviceOk = loaded && health?.status === "ok";
  const version = health?.version ? `v${health.version}` : "—";
  const perf =
    health?.performance_mode && PERF_ZH[health.performance_mode]
      ? PERF_ZH[health.performance_mode]
      : "—";
  const uptime = health ? fmtUptime(health.uptime_s) : "—";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-w-0">
      <section className={CARD_CLS}>
        <div className="flex items-center justify-between gap-3 min-w-0">
          <h3 className={TITLE_CLS}>版本与应用</h3>
          <StatusPill loaded={loaded} ok={!!serviceOk} />
        </div>
        <div className="flex flex-col gap-2 min-w-0">
          <InfoRow label="版本号" mono>
            {version}
          </InfoRow>
          <InfoRow label="性能模式">{perf}</InfoRow>
          <InfoRow label="Python 运行时" mono>
            {health?.python ?? "—"}
          </InfoRow>
          <InfoRow label="运行时长" mono>
            {uptime}
          </InfoRow>
        </div>
        <p className={BODY_CLS}>
          由本地 ai-service 驱动：语音、记忆、任务与执行器都在本机提供服务。
        </p>
      </section>

      <section className={CARD_CLS}>
        <h3 className={TITLE_CLS}>本地优先与数据边界</h3>
        <p className={BODY_CLS}>
          栖灵默认在本机运行：服务、模型调用与文件处理均可在本地完成，数据不出设备；只有你主动授权的网络任务才会访问外部服务。
        </p>
        <div className="flex flex-col gap-1.5 min-w-0">
          {DIRS.map((d) => (
            <div
              key={d.label}
              className="flex items-center justify-between gap-3 min-w-0"
            >
              <span className="text-xs text-muted shrink-0">{d.label}</span>
              <span className="text-xs font-mono text-ink text-right min-w-0 break-all">
                {d.path}
              </span>
            </div>
          ))}
        </div>
        <p className={BODY_CLS}>
          密钥与 API key 仅保存在本地配置中，不进入代码库或提交记录。
        </p>
      </section>

      <section className={CARD_CLS}>
        <h3 className={TITLE_CLS}>文档与更新日志</h3>
        <p className={BODY_CLS}>
          项目文档见{" "}
          <span className="font-mono text-ink break-all">docs/README.md</span>、
          <span className="font-mono text-ink break-all">
            docs/PROJECT-ROADMAP.md
          </span>
          、
          <span className="font-mono text-ink break-all">
            docs/HANDOVER-2026-09-13.md
          </span>
          。
        </p>
        <p className={BODY_CLS}>
          更新日志详见{" "}
          <span className="font-mono text-ink break-all">
            docs/PROJECT-ROADMAP.md
          </span>{" "}
          与提交记录。
        </p>
      </section>

      <section className={CARD_CLS}>
        <h3 className={TITLE_CLS}>致谢与第三方</h3>
        <p className={BODY_CLS}>
          栖灵由本地优先的组件与工具构建，核心能力均可脱离云端在本机运行：
        </p>
        <ul className="flex flex-wrap gap-1.5">
          {STACK.map((name) => (
            <li
              key={name}
              className="rounded-full bg-surface-secondary px-2.5 py-1 text-xs text-ink"
            >
              {name}
            </li>
          ))}
        </ul>
        <p className={BODY_CLS}>
          其中 Codex ACP 负责执行器通信，FastAPI 提供本地服务，React/Vite
          构建主界面，Tauri 承载桌面端，Tailwind CSS 提供界面样式。
        </p>
      </section>
    </div>
  );
}
