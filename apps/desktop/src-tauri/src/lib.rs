//! 栖灵桌面运行时（Step 1：启动本地 AI 服务 + 打开默认浏览器主界面）。

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
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

mod widget;

const SERVICE_PORT: u16 = 8736;
/// 主界面可见性事件：主界面据此让出/收回语音租约，挂件据此立即重探租约。
const MAIN_UI_VISIBILITY: &str = "main-ui-visibility";
/// 挂件要求主界面切到指定会话：主界面据此加载长回复所在的会话。
const MAIN_UI_OPEN_CONVERSATION: &str = "main-ui-open-conversation";
const SERVICE_START_TIMEOUT: Duration = Duration::from_secs(30);
const SERVICE_PROBE_TIMEOUT: Duration = Duration::from_secs(3);
const SERVICE_PORT_GRACE: Duration = Duration::from_millis(1500);
const LOG_TAIL_CHARS: usize = 4000;

struct Shared {
    child: Option<Child>,
    /// QILING_HOME：开发态=仓库根；打包态=Application Support 里的可写副本
    home_root: Option<PathBuf>,
    /// 打包态冻结的 ai-service 二进制；None 时走开发态 .venv python
    sidecar_bin: Option<PathBuf>,
    spawn_error: Option<String>,
    log_path: Option<PathBuf>,
}

/// 打包/开发两种服务布局解析结果（首启时把只读模板拷成可写 home）。
fn resolve_layout(app: &AppHandle) -> Shared {
    use tauri::Manager;

    // 打包态：Resources/home-template + Resources/runtime/ai-service
    if let Ok(res_dir) = app.path().resource_dir() {
        let template = res_dir.join("home-template");
        #[cfg(target_os = "windows")]
        let bin = res_dir.join("runtime").join("ai-service").join("ai-service.exe");
        #[cfg(not(target_os = "windows"))]
        let bin = res_dir.join("runtime").join("ai-service").join("ai-service");
        if template.is_dir() && bin.is_file() {
            let mut shared = Shared {
                child: None,
                home_root: None,
                sidecar_bin: Some(bin),
                spawn_error: None,
                log_path: None,
            };
            match app.path().app_data_dir() {
                Ok(home) => {
                    if !home.join(".seed-version").is_file() {
                        if let Err(error) = copy_dir_recursive(&template, &home) {
                            shared.spawn_error = Some(format!("初始化应用数据失败: {error}"));
                            return shared;
                        }
                    }
                    shared.home_root = Some(home);
                }
                Err(error) => shared.spawn_error = Some(format!("定位应用数据目录失败: {error}")),
            }
            return shared;
        }
    }

    // 开发态：仓库根 + .venv
    Shared {
        child: None,
        home_root: discover_repo_root(),
        sidecar_bin: None,
        spawn_error: None,
        log_path: None,
    }
}

/// 递归拷贝首启模板（模板内无符号链接，按普通文件复制即可）。
fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let target = dst.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_recursive(&entry.path(), &target)?;
        } else {
            let _ = fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
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
    fn new(app: &AppHandle) -> Self {
        ChildState(Mutex::new(resolve_layout(app)))
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
            repo_ok: shared.home_root.is_some(),
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

/// 首启向导是否还没完成（/api/setup/status 的 completed=false）。
/// 任何不确定（连不上/响应异常）都按 false 处理，绝不能因为一次探测失败就弹窗。
fn setup_incomplete() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], SERVICE_PORT)),
        SERVICE_PROBE_TIMEOUT,
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(SERVICE_PROBE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(SERVICE_PROBE_TIMEOUT));
    if stream
        .write_all(b"GET /api/setup/status HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let Some(body) = response.split_once("\r\n\r\n").map(|(_, body)| body) else {
        return false;
    };
    serde_json::from_str::<serde_json::Value>(body)
        .ok()
        .and_then(|value| value.get("completed").and_then(|item| item.as_bool()))
        == Some(false)
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
    if let Ok(home) = std::env::var("QILING_HOME") {
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
                "端口 {SERVICE_PORT} 已被其他进程占用，栖灵本地服务未启动。请先关闭占用进程或运行退出脚本。"
            ));
            return;
        }
    }

    let Some(home) = shared.home_root.clone() else {
        shared.spawn_error = Some("未找到运行目录（services/ai-service 或应用数据目录）".into());
        return;
    };

    // 开发态：仓库内 .venv 跑 uvicorn；打包态：Resources 里的冻结 sidecar
    #[cfg(target_os = "windows")]
    let python = home.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(target_os = "windows"))]
    let python = home.join(".venv").join("bin").join("python");
    let is_packaged = shared.sidecar_bin.is_some();
    if !is_packaged && !python.is_file() {
        shared.spawn_error = Some("缺少 .venv，请先运行 scripts/setup.sh 初始化环境".to_string());
        return;
    }

    let service_dir = home.join("services").join("ai-service");
    let run_dir = home.join("data").join("run");
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
        "\n--- Qiling AI service start (unix={timestamp}) ---"
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
    let mut command = match shared.sidecar_bin.clone() {
        Some(bin) => {
            let mut command = Command::new(bin);
            command
                .env("QILING_HOME", &home)
                .env("QILING_HOST", "127.0.0.1")
                .env("QILING_PORT", &port);
            command
        }
        None => {
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
                .env("QILING_HOME", &home);
            command
        }
    };
    command.stdin(Stdio::null()).stdout(stdout).stderr(stderr);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(target_os = "windows"))]
    {
        use std::os::unix::process::CommandExt;
        // 让 uvicorn 单独成组（PGID=子进程PID），退出时按整组回收，
        // 避免任何子进程残留继续占用端口/麦克风。
        command.process_group(0);
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

fn open_main_ui_window(
    app: &AppHandle,
    page: Option<String>,
    conversation: Option<String>,
) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{SERVICE_PORT}/{}", page_fragment(page));
    if let Some(window) = app.get_webview_window("main_ui") {
        let target: tauri::Url = url.parse().map_err(|e| format!("主界面地址无效: {e}"))?;
        // 目标地址与当前一致时只显示不导航：避免重载杀掉刚建立的租约心跳。
        let same_url = window
            .url()
            .map(|current| current.as_str() == target.as_str())
            .unwrap_or(false);
        if !same_url {
            window
                .navigate(target)
                .map_err(|e| format!("切换主界面页面失败: {e}"))?;
        }
        let _ = window.show();
        let _ = window.set_focus();
        let _ = app.emit(MAIN_UI_VISIBILITY, true);
        if let Some(id) = conversation {
            let _ = app.emit(MAIN_UI_OPEN_CONVERSATION, id);
        }
        return Ok(());
    }
    let target: tauri::Url = url.parse().map_err(|e| format!("主界面地址无效: {e}"))?;
    let window = WebviewWindowBuilder::new(app, "main_ui", WebviewUrl::External(target))
        .title("栖灵主界面")
        .inner_size(1200.0, 800.0)
        .min_inner_size(900.0, 640.0)
        .center()
        .build()
        .map_err(|e| format!("创建主界面窗口失败: {e}"))?;
    let _ = window.show();
    let _ = window.set_focus();
    let _ = app.emit(MAIN_UI_VISIBILITY, true);
    if let Some(id) = conversation {
        let _ = app.emit(MAIN_UI_OPEN_CONVERSATION, id);
    }
    Ok(())
}

/// 查询主界面窗口当前是否真实可见（权威状态，供挂件/主页自愈漏接事件）。
#[tauri::command]
fn main_ui_visible(app: AppHandle) -> bool {
    app.get_webview_window("main_ui")
        .map(|window| window.is_visible().unwrap_or(false))
        .unwrap_or(false)
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
fn open_main_ui(
    app: AppHandle,
    state: State<'_, ChildState>,
    page: Option<String>,
    conversation: Option<String>,
) -> Result<(), String> {
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
    open_main_ui_window(&app, page, conversation)
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
                #[cfg(not(target_os = "windows"))]
                {
                    // 服务以新进程组启动；对负 PID（= 整个进程组）发 TERM，
                    // 再回收主进程，避免任何子进程残留。
                    let group = format!("-{}", child.id());
                    let _ = Command::new("/bin/kill")
                        .args(["-TERM", &group])
                        .output();
                }
                let _ = child.kill();
                let _ = child.wait();
                #[cfg(not(target_os = "windows"))]
                kill_listeners_on_port(SERVICE_PORT);
            }
        }
    }
}

/// 端口兜底：回收仍在监听本项目服务端口的进程（uvicorn 偶发漏网时）。
/// 只作用于 127.0.0.1 的该端口，不触碰其它程序。
#[cfg(not(target_os = "windows"))]
fn kill_listeners_on_port(port: u16) {
    let endpoint = format!("TCP:127.0.0.1:{port}");
    let output = match Command::new("/usr/sbin/lsof")
        .args(["-t", "-i", &endpoint, "-sTCP:LISTEN"])
        .output()
    {
        Ok(value) => value,
        Err(_) => return,
    };
    for pid in String::from_utf8_lossy(&output.stdout).split_whitespace() {
        let _ = Command::new("/bin/kill").args(["-TERM", pid]).output();
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(ChildState::new(app.handle()));
            let launcher_needed = !ensure_service_for_app(app.handle());
            if launcher_needed {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                }
            }
            if let Err(err) = widget::restore_widget_position(app.handle()) {
                eprintln!("Qiling widget positioning failed: {err}");
            }
            app.manage(widget::WidgetRuntimeState::new(app.handle().clone()));

            // 系统托盘图标 + 右键菜单
            let open_item = MenuItem::with_id(app, "open", "打开主界面", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出栖灵", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            // 图标直接编进二进制：安装包不再需要释放 icons/ 目录，
            // 资源漏装时主进程也不会 panic（Windows 验收 P0-1 根因）。
            let icon = Image::from_bytes(include_bytes!("../icons/32x32.png"))
                .expect("embedded tray icon png is valid");

            TrayIconBuilder::new()
                .icon(icon)
                .tooltip("栖灵")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "open" => {
                        if ensure_service_for_app(app) {
                            let _ = open_main_ui_window(app, None, None);
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

            // 首启向导未完成时自动弹出主界面（向导本身在 web 端渲染）。
            // sidecar 冷启最多等 SERVICE_START_TIMEOUT；用户点过「跳过」后 completed=true 不再弹。
            let startup_handle = app.handle().clone();
            thread::spawn(move || {
                let deadline = Instant::now() + SERVICE_START_TIMEOUT;
                while !service_health_ok() {
                    if Instant::now() >= deadline {
                        return;
                    }
                    thread::sleep(Duration::from_millis(300));
                }
                if !setup_incomplete() {
                    return;
                }
                let handle = startup_handle.clone();
                let _ = startup_handle.run_on_main_thread(move || {
                    let _ = open_main_ui_window(&handle, None, None);
                });
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ensure_service,
            service_status,
            open_main_ui,
            main_ui_visible,
            widget::get_widget_preferences,
            widget::set_widget_auto_hide,
            widget::set_widget_scale,
            widget::set_widget_visible_edges,
            widget::set_widget_interactive_area,
            widget::start_widget_drag,
            widget::cancel_widget_drag,
            widget::finish_widget_drag,
            widget::resize_widget_height,
            widget::system_idle_seconds,
            quit_app
        ])
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                if window.label() == "main_ui" {
                    api.prevent_close();
                    let _ = window.hide();
                    // 隐藏（关闭按钮走 hide，不是最小化/失焦）= 用户大概率转闲聊：
                    // 通知主界面让出语音租约，挂件才能自动接管「听」。
                    let _ = window.app_handle().emit(MAIN_UI_VISIBILITY, false);
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
