//! DeskMate 桌面运行时（Step 1：启动本地 AI 服务 + 打开默认浏览器主界面）。
//!
//! 后续 Step 2 将在此加入挂件透明窗口、状态动画等，对外接口保持一致。

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Manager, State, WindowEvent};

const SERVICE_PORT: u16 = 8736;
const WIDGET_EDGE_MARGIN: i32 = 18;

struct Shared {
    child: Option<Child>,
    repo_root: Option<PathBuf>,
    spawn_error: Option<String>,
}

struct ChildState(Mutex<Shared>);

#[derive(Serialize, Clone)]
struct ServiceStatus {
    running: bool,
    url: String,
    repo_ok: bool,
    spawn_error: Option<String>,
}

impl ChildState {
    fn new() -> Self {
        ChildState(Mutex::new(Shared {
            child: None,
            repo_root: discover_repo_root(),
            spawn_error: None,
        }))
    }

    fn snapshot(&self) -> ServiceStatus {
        let mut shared = self.0.lock().expect("child state lock poisoned");
        let running = shared
            .child
            .as_mut()
            .and_then(|c| c.try_wait().ok().flatten())
            .is_none()
            && shared.child.is_some();
        ServiceStatus {
            running,
            url: format!("http://127.0.0.1:{SERVICE_PORT}/"),
            repo_ok: shared.repo_root.is_some(),
            spawn_error: shared.spawn_error.clone(),
        }
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
    cur.pop(); // 从可执行文件所在目录开始向上找
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
        return;
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
        shared.spawn_error =
            Some("缺少 .venv，请先运行 scripts/setup.sh 初始化环境".to_string());
        return;
    }

    let service_dir = root.join("services").join("ai-service");
    let port = SERVICE_PORT.to_string();
    match Command::new(&python)
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
        .spawn()
    {
        Ok(child) => {
            shared.child = Some(child);
            shared.spawn_error = None;
        }
        Err(e) => shared.spawn_error = Some(format!("启动 AI 服务失败: {e}")),
    }
}

fn open_url_in_browser(url: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg(url).spawn();
    #[cfg(target_os = "windows")]
    let result = Command::new("cmd").args(["/C", "start", "", url]).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let result = Command::new("xdg-open").arg(url).spawn();
    result.map(|_| ()).map_err(|e| format!("打开浏览器失败: {e}"))
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
fn open_main_ui() -> Result<(), String> {
    open_url_in_browser(&format!("http://127.0.0.1:{SERVICE_PORT}/"))
}

fn move_widget_to_bottom_right(app: &AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("widget")
        .ok_or_else(|| "找不到挂件窗口".to_string())?;
    let monitor = match window.current_monitor() {
        Ok(Some(monitor)) => monitor,
        _ => window
            .primary_monitor()
            .map_err(|e| format!("读取主显示器失败: {e}"))?
            .ok_or_else(|| "无法识别显示器".to_string())?,
    };
    let size = window
        .inner_size()
        .map_err(|e| format!("读取挂件尺寸失败: {e}"))?;
    let area = monitor.work_area();
    let x = area.position.x + area.size.width as i32 - size.width as i32 - WIDGET_EDGE_MARGIN;
    let y = area.position.y + area.size.height as i32 - size.height as i32 - WIDGET_EDGE_MARGIN;
    window
        .set_position(tauri::PhysicalPosition::new(
            x.max(area.position.x),
            y.max(area.position.y),
        ))
        .map_err(|e| format!("移动挂件失败: {e}"))
}

#[tauri::command]
fn place_widget_bottom_right(app: AppHandle) -> Result<(), String> {
    move_widget_to_bottom_right(&app)
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(ChildState::new());
            // 启动即拉起本地 AI 服务（幂等，健康状态由前端轮询）
            let state = app.state::<ChildState>();
            if let Ok(mut shared) = state.0.lock() {
                start_service(&mut shared);
            }
            if let Err(err) = move_widget_to_bottom_right(app.handle()) {
                eprintln!("DeskMate widget positioning failed: {err}");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ensure_service,
            service_status,
            open_main_ui,
            place_widget_bottom_right
        ])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                let app = window.app_handle().clone();
                kill_child(&app);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // 兜底：应用进程退出时确保 AI 服务被回收
            if let tauri::RunEvent::Exit = event {
                kill_child(app);
            }
        });
}
