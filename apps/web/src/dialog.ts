import { isTauri } from "@tauri-apps/api/core";
import { ask } from "@tauri-apps/plugin-dialog";

/** 确认框：Tauri 窗口的 WKWebView 没实现 window.confirm（恒返回 true），必须走原生 ask；浏览器保持原样。 */
export async function confirmText(message: string, title = "确认"): Promise<boolean> {
  if (isTauri()) return ask(message, { title, kind: "warning" });
  return window.confirm(message);
}
