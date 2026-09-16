//! DeskMate 桌面运行时（Step 1：启动本地 AI 服务 + 打开默认浏览器主界面）。

use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

mod widget;

const SERVICE_PORT: u16 = 8736;
const SERVICE_START_TIMEOUT: Duration = Duration::from_secs(15);
const SERVICE_PROBE_TIMEOUT: Duration = Duration::from_secs(3);
const SERVICE_PORT_GRACE: Duration = Duration::from_millis(1500);
const LOG_TAIL_CHARS: usize = 4000;

struct Shared {
    child: Option<Child>,
    repo_root: Option<PathBuf>,
    spawn_error: Option<String>,
    log_path: Option<PathBuf>,
}

struct ChildState(Mutex<Shared>);

#[derive(Serialize, Clone)]
struct ServiceStatus {
    running: bool,
    url: String,
    repo_ok: bool,
    spawn_error: Option<String>,
    log_path: Option<String>,
}

impl ChildState {
    fn new() -> Self {
        ChildState(Mutex::new(Shared {
            child: None,
            repo_root: discover_repo_root(),
            spawn_error: None,
            log_path: None,
        }))
    }

    fn snapshot(&self) -> ServiceStatus {
        let mut shared = self.0.lock().expect("child state lock poisoned");
        let healthy = service_health_ok();
        let mut exited = None;
        if let Some(child) = shared.child.as_mut() {
            match child.try_wait() {
                Ok(status) => exited = status,
                Err(error) => {
                    shared.spawn_error = Some(format!("读取 AI 服务状态失败: {error}"));
                    shared.child = None;
                }
            }
        }
        if let Some(status) = exited {
            shared.child = None;
            if !healthy {
                set_service_failure(&mut shared, format!("AI 服务已退出（{status}）"));
            }
        }
        if healthy {
            shared.spawn_error = None;
        }
        let running = healthy || shared.child.is_some();
        ServiceStatus {
            running,
            url: format!("http://127.0.0.1:{SERVICE_PORT}/"),
            repo_ok: shared.repo_root.is_some(),
            spawn_error: shared.spawn_error.clone(),
            log_path: shared
                .log_path
                .as_ref()
                .map(|path| path.display().to_string()),
        }
    }
}

fn service_port_open() -> bool {
    TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], SERVICE_PORT)),
        SERVICE_PROBE_TIMEOUT,
    )
    .is_ok()
}

fn service_health_ok() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], SERVICE_PORT)),
        SERVICE_PROBE_TIMEOUT,
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(SERVICE_PROBE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(SERVICE_PROBE_TIMEOUT));
    if stream
        .write_all(b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200")
}

fn tail_text(text: &str) -> Option<String> {
    let text = text.trim();
    if text.is_empty() {
        return None;
    }
    let mut start = text.len().saturating_sub(LOG_TAIL_CHARS);
    while !text.is_char_boundary(start) {
        start += 1;
    }
    Some(text[start..].to_string())
}

fn read_log_tail(path: &Path) -> Option<String> {
    tail_text(&fs::read_to_string(path).ok()?)
}

fn set_service_failure(shared: &mut Shared, message: String) {
    let message = match shared.log_path.as_deref().and_then(read_log_tail) {
        Some(log_tail) => format!("{message}\n最近日志：\n{log_tail}"),
        None => message,
    };
    shared.spawn_error = Some(message);
}

fn wait_for_service(shared: &mut Shared) {
    let deadline = Instant::now() + SERVICE_START_TIMEOUT;
    loop {
        if service_health_ok() {
            shared.spawn_error = None;
            return;
        }

        let mut exited = None;
        if let Some(child) = shared.child.as_mut() {
            match child.try_wait() {
                Ok(status) => exited = status,
                Err(error) => {
                    set_service_failure(shared, format!("读取 AI 服务进程状态失败: {error}"));
                    return;
                }
            }
        }
        if let Some(status) = exited {
            shared.child = None;
            set_service_failure(shared, format!("AI 服务启动失败（进程退出: {status}）"));
            return;
        }

        if Instant::now() >= deadline {
            set_service_failure(
                shared,
                format!("AI 服务启动超时（{} 秒）", SERVICE_START_TIMEOUT.as_secs()),
            );
            return;
        }
        thread::sleep(Duration::from_millis(150));
    }
}

fn discover_repo_root() -> Option<PathBuf> {
    if let Ok(home) = std::env::var("DESKMATE_HOME") {
        let p = PathBuf::from(home);
        if p.join("services").join("ai-service").is_dir() {
            return Some(p);
        }
    }
    let mut cur = std::env::current_exe().ok()?;
    cur.pop();
    loop {
        if cur.join("services").join("ai-service").is_dir() {
            return Some(cur);
        }
        if !cur.pop() {
            break;
        }
    }
    None
}

fn start_service(shared: &mut Shared) {
    let already_running = shared
        .child
        .as_mut()
        .and_then(|c| c.try_wait().ok().flatten())
        .is_none()
        && shared.child.is_some();
    if already_running {
        wait_for_service(shared);
        return;
    }

    if service_health_ok() {
        shared.spawn_error = None;
        return;
    }
    if service_port_open() {
        let deadline = Instant::now() + SERVICE_PORT_GRACE;
        while Instant::now() < deadline {
            if service_health_ok() {
                shared.spawn_error = None;
                return;
            }
            if !service_port_open() {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        if service_port_open() {
            shared.spawn_error = Some(format!(
                "端口 {SERVICE_PORT} 已被其他进程占用，DeskMate 本地服务未启动。请先关闭占用进程或运行退出脚本。"
            ));
            return;
        }
    }

    let Some(root) = shared.repo_root.clone() else {
        shared.spawn_error = Some("未找到项目根目录（services/ai-service）".into());
        return;
    };

    #[cfg(target_os = "windows")]
    let python = root.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(target_os = "windows"))]
    let python = root.join(".venv").join("bin").join("python");
    if !python.is_file() {
        shared.spawn_error = Some("缺少 .venv，请先运行 scripts/setup.sh 初始化环境".to_string());
        return;
    }

    let service_dir = root.join("services").join("ai-service");
    let run_dir = root.join("data").join("run");
    if let Err(error) = fs::create_dir_all(&run_dir) {
        shared.spawn_error = Some(format!("创建运行日志目录失败: {error}"));
        return;
    }
    let log_path = run_dir.join("ai-service.log");
    let mut log_file = match OpenOptions::new().create(true).append(true).open(&log_path) {
        Ok(file) => file,
        Err(error) => {
            shared.spawn_error = Some(format!("打开 AI 服务日志失败: {error}"));
            return;
        }
    };
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    let _ = writeln!(
        log_file,
        "\n--- DeskMate AI service start (unix={timestamp}) ---"
    );
    let stdout = match log_file.try_clone() {
        Ok(file) => Stdio::from(file),
        Err(error) => {
            shared.spawn_error = Some(format!("准备 AI 服务日志输出失败: {error}"));
            return;
        }
    };
    let stderr = Stdio::from(log_file);

    let port = SERVICE_PORT.to_string();
    let mut command = Command::new(&python);
    command
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port,
        ])
        .current_dir(&service_dir)
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => {
            shared.child = Some(child);
            shared.spawn_error = None;
            shared.log_path = Some(log_path);
            wait_for_service(shared);
        }
        Err(e) => {
            shared.log_path = Some(log_path);
            set_service_failure(shared, format!("启动 AI 服务失败: {e}"));
        }
    }
}

fn open_main_ui_window(app: &AppHandle, page: Option<String>) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{SERVICE_PORT}/{}", page_fragment(page));
    if let Some(window) = app.get_webview_window("main_ui") {
        window
            .navigate(url.parse().map_err(|e| format!("主界面地址无效: {e}"))?)
            .map_err(|e| format!("切换主界面页面失败: {e}"))?;
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    WebviewWindowBuilder::new(app, "main_ui", WebviewUrl::External(url.parse().map_err(|e| format!("主界面地址无效: {e}"))?))
        .title("DeskMate 主界面")
        .inner_size(1200.0, 800.0)
        .min_inner_size(900.0, 640.0)
        .center()
        .build()
        .map(|_| ())
        .map_err(|e| format!("创建主界面窗口失败: {e}"))
}

#[tauri::command]
fn ensure_service(state: State<'_, ChildState>) -> Result<ServiceStatus, String> {
    {
        let mut shared = state.0.lock().map_err(|_| "服务状态锁不可用".to_string())?;
        start_service(&mut shared);
    }
    Ok(state.snapshot())
}

#[tauri::command]
fn service_status(state: State<'_, ChildState>) -> Result<ServiceStatus, String> {
    Ok(state.snapshot())
}

#[tauri::command]
fn open_main_ui(app: AppHandle, state: State<'_, ChildState>, page: Option<String>) -> Result<(), String> {
    let log_path = {
        let mut shared = state.0.lock().map_err(|_| "服务状态锁不可用".to_string())?;
        start_service(&mut shared);
        shared
            .log_path
            .as_ref()
            .map(|path| path.display().to_string())
    };
    eprintln!("[open_main_ui] health check start");
    if !service_health_ok() {
        eprintln!("[open_main_ui] health check FAILED");
        return Err(match log_path {
            Some(path) => format!("AI 服务尚未就绪，请查看日志：{path}"),
            None => "AI 服务尚未就绪".to_string(),
        });
    }
    open_main_ui_window(&app, page)
}

/// 页面名 → URL 片段（`chat` → `#/chat`）；只放行纯字母，其余一律回到主页。
fn page_fragment(page: Option<String>) -> String {
    match page {
        Some(value)
            if !value.is_empty()
                && value.len() <= 16
                && value.chars().all(|c| c.is_ascii_lowercase()) =>
        {
            format!("#/{value}")
        }
        _ => String::new(),
    }
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    kill_child(&app);
    app.exit(0);
}

fn kill_child(app: &AppHandle) {
    if let Some(state) = app.try_state::<ChildState>() {
        if let Ok(mut shared) = state.0.lock() {
            if let Some(mut child) = shared.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn ensure_service_for_app(app: &AppHandle) -> bool {
    if let Some(state) = app.try_state::<ChildState>() {
        if let Ok(mut shared) = state.0.lock() {
            start_service(&mut shared);
        }
    }
    service_health_ok()
}

/// 查找托盘图标：优先 src-tauri/icons/32x32.png（开发模式），
/// 其次可执行文件同级 icons/32x32.png（打包后）。
fn find_tray_icon() -> Option<PathBuf> {
    // 开发模式：crate manifest dir
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_icon = manifest_dir.join("icons").join("32x32.png");
    if dev_icon.is_file() {
        return Some(dev_icon);
    }
    // 打包模式：可执行文件同级
    let mut exe = std::env::current_exe().ok()?;
    exe.pop();
    let prod_icon = exe.join("icons").join("32x32.png");
    if prod_icon.is_file() {
        return Some(prod_icon);
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(ChildState::new());
            let launcher_needed = !ensure_service_for_app(app.handle());
            if launcher_needed {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                }
            }
            if let Err(err) = widget::restore_widget_position(app.handle()) {
                eprintln!("DeskMate widget positioning failed: {err}");
            }
            app.manage(widget::WidgetRuntimeState::new(app.handle().clone()));

            // 系统托盘图标 + 右键菜单
            let open_item = MenuItem::with_id(app, "open", "打开主界面", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出 DeskMate", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            let icon_path = find_tray_icon().expect("tray icon not found: icons/32x32.png");
            let icon = Image::from_path(&icon_path).expect("failed to load tray icon");

            TrayIconBuilder::new()
                .icon(icon)
                .tooltip("DeskMate")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "open" => {
                        if ensure_service_for_app(app) {
                            let _ = open_main_ui_window(app, None);
                        } else if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                        }
                    }
                    "quit" => {
                        kill_child(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ensure_service,
            service_status,
            open_main_ui,
            widget::get_widget_preferences,
            widget::set_widget_auto_hide,
            widget::set_widget_scale,
            widget::set_widget_visible_edges,
            widget::set_widget_interactive_area,
            widget::start_widget_drag,
            widget::cancel_widget_drag,
            widget::finish_widget_drag,
            widget::resize_widget_height,
            quit_app
        ])
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                if window.label() == "main_ui" {
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    let app = window.app_handle().clone();
                    kill_child(&app);
                }
            }
            WindowEvent::Moved(_) if window.label() == "widget" => {
                if let Some(state) = window
                    .app_handle()
                    .try_state::<widget::WidgetRuntimeState>()
                {
                    state.notify_moved();
                }
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                kill_child(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{page_fragment, tail_text};

    #[test]
    fn log_tail_keeps_utf8_and_ignores_blank_text() {
        assert_eq!(tail_text(" \n\t"), None);
        assert_eq!(tail_text("服务启动失败").as_deref(), Some("服务启动失败"));
    }

    #[test]
    fn page_fragment_only_allows_plain_page_names() {
        assert_eq!(page_fragment(Some("chat".to_string())), "#/chat");
        assert_eq!(page_fragment(Some("memory".to_string())), "#/memory");
        assert_eq!(page_fragment(None), "");
        assert_eq!(page_fragment(Some(String::new())), "");
        assert_eq!(page_fragment(Some("Chat".to_string())), "");
        assert_eq!(page_fragment(Some("../evil".to_string())), "");
        assert_eq!(page_fragment(Some("chat?x=1".to_string())), "");
        assert_eq!(page_fragment(Some("a".repeat(17))), "");
    }
}
