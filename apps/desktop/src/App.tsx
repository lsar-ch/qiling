import { lazy, Suspense, useEffect, useState } from "react";

const Launcher = lazy(() => import("./components/Launcher"));
const Widget = lazy(() => import("./components/Widget"));

type WindowKind = "launcher" | "widget" | "browser";

function detectKind(): Promise<WindowKind> {
  if (new URLSearchParams(window.location.search).get("deskmate") === "widget") {
    return Promise.resolve("widget");
  }
  return import("@tauri-apps/api/window")
    .then(({ getCurrentWindow }) =>
      getCurrentWindow().label === "widget" ? "widget" : "launcher",
    )
    .catch(() => "browser");
}

export default function App() {
  const [kind, setKind] = useState<WindowKind | null>(null);

  useEffect(() => {
    let cancelled = false;
    void detectKind().then((k) => {
      if (!cancelled) setKind(k);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (kind === null) {
    return <div className="boot">DeskMate 启动中…</div>;
  }

  return (
    <Suspense fallback={<div className="boot">加载中…</div>}>
      {kind === "widget" ? <Widget /> : <Launcher />}
    </Suspense>
  );
}
