import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { pollHealth } from "../api";
import "./launcher.css";

interface ServiceStatus {
  running: boolean;
  url: string;
  repo_ok: boolean;
  spawn_error: string | null;
}

export default function Launcher() {
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [healthy, setHealthy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [widgetHidden, setWidgetHidden] = useState(false);
  const [msg, setMsg] = useState("");

  const refreshStatus = useCallback(async () => {
    const s = await invoke<ServiceStatus>("service_status");
    setStatus(s);
    if (s.url) setHealthy(await pollHealth(s.url));
  }, []);

  useEffect(() => {
    void refreshStatus();
    const timer = setInterval(() => void refreshStatus(), 5000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  const startService = async () => {
    setBusy(true);
    setMsg("正在启动本地 AI 服务…");
    try {
      const s = await invoke<ServiceStatus>("ensure_service");
      setStatus(s);
      setMsg(s.spawn_error ?? (s.running ? "已启动，等待健康检查" : "未运行"));
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 500));
        if (await pollHealth(s.url)) {
          setHealthy(true);
          setMsg("本地服务运行正常");
          break;
        }
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const openUi = async () => {
    try {
      await invoke("open_main_ui");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleWidget = async () => {
    try {
      const widget = await WebviewWindow.getByLabel("widget");
      if (!widget) throw new Error("找不到挂件窗口");
      if (widgetHidden) {
        await widget.show();
        await widget.setFocus();
        setWidgetHidden(false);
      } else {
        await widget.hide();
        setWidgetHidden(true);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="l-shell">
      <header className="l-head">
        <span className="dot" data-state={healthy ? "ok" : "off"} />
        <div>
          <h1>DeskMate</h1>
          <p className="sub">桌面运行时 · Step 2（挂件 + 主界面）</p>
        </div>
      </header>

      <section className="panel">
        <h2>本地 AI 服务</h2>
        <div className="kv">
          <span>状态</span>
          <b className={healthy ? "ok" : "muted"}>
            {healthy ? "正常" : status?.running ? "启动中…" : "未运行"}
          </b>
          <span>地址</span>
          <b className="mono">{status?.url ?? "—"}</b>
          <span>挂件</span>
          <b className="muted">{widgetHidden ? "已隐藏" : "显示中"}</b>
        </div>
        {status?.spawn_error && <p className="err">{status.spawn_error}</p>}
        {msg && <p className="msg">{msg}</p>}
      </section>

      <div className="actions">
        <button className="primary" onClick={() => void startService()} disabled={busy}>
          {busy ? "启动中…" : "启动本地服务"}
        </button>
        <button onClick={() => void openUi()} disabled={!healthy}>
          在浏览器打开主界面
        </button>
        <button onClick={() => void toggleWidget()}>
          {widgetHidden ? "显示挂件" : "隐藏挂件"}
        </button>
      </div>

      <footer>
        双击挂件即可打开主界面；关闭启动器会停止 AI 服务。
        <br />
        初始化环境请先运行 <code>scripts/setup.sh</code>。
      </footer>
    </div>
  );
}
