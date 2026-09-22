use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
#[cfg(target_os = "windows")]
use std::sync::Mutex;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize};

const WIDGET_LABEL: &str = "widget";
const WIDGET_EDGE_MARGIN: i32 = 18;
const WIDGET_EDGE_TRIGGER: i32 = 44;
// ponytail: portable Tauri has no drag-release event, so quiet time approximates the end.
// Replace it with a platform drag-end event if pausing during a drag feels premature.
const WIDGET_DRAG_SETTLE_DELAY: Duration = Duration::from_millis(350);
const WIDGET_MIN_SCALE: f64 = 0.75;
const WIDGET_MAX_SCALE: f64 = 2.0;
const WIDGET_PREFERENCES_FILE: &str = "widget.json";
// 贴边隐藏后让透明区域不再拦截鼠标点击（目前只在 Windows 分支实现）。
// 若隐藏态的挂件变得难以抓取，把这个开关改成 false 即可整体关掉该行为。
#[cfg(target_os = "windows")]
const WIDGET_POINTER_PASS_THROUGH: bool = true;
#[cfg(target_os = "windows")]
const WIDGET_POINTER_POLL_INTERVAL: Duration = Duration::from_millis(80);
// 光标落在可交互区域外这么多个逻辑像素才算“不打算抓挂件”，避免边缘抖动。
#[cfg(target_os = "windows")]
const WIDGET_POINTER_GRAB_MARGIN: f64 = 20.0;

#[cfg(target_os = "macos")]
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn CGEventSourceButtonState(state_id: i32, button: u32) -> bool;
    fn CGEventSourceSecondsSinceLastEventType(state_id: i32, event_type: u32) -> f64;
}

#[cfg(target_os = "macos")]
fn primary_mouse_down() -> bool {
    // Combined session state, left mouse button. No input monitoring permission is required.
    unsafe { CGEventSourceButtonState(0, 0) }
}

/// 系统无输入空闲秒数；macOS 无需输入监控权限，只读组合会话状态。
#[cfg(target_os = "macos")]
fn system_idle_seconds_impl() -> f64 {
    // kCGEventSourceStateCombinedSessionState = 0，kCGAnyInputEventType = !0
    unsafe { CGEventSourceSecondsSinceLastEventType(0, !0u32) }
}

#[cfg(target_os = "windows")]
#[link(name = "user32")]
extern "system" {
    fn GetAsyncKeyState(v_key: i32) -> i16;
    fn GetCursorPos(point: *mut ScreenPoint) -> i32;
}

/// 屏幕物理像素坐标，布局与 Windows 的 POINT 一致。
#[cfg(target_os = "windows")]
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
struct ScreenPoint {
    x: i32,
    y: i32,
}

/// VK_LBUTTON = 0x01，返回值最高位为 1 表示当前按下。
/// 旧实现在非 macOS 平台直接返回 false，于是 settle_worker 里
/// “等鼠标真的松开”那段循环在 Windows 上完全空转。
#[cfg(target_os = "windows")]
fn primary_mouse_down() -> bool {
    unsafe { (GetAsyncKeyState(0x01) as u16 & 0x8000) != 0 }
}

/// Windows 输入空闲秒数：GetLastInputInfo 返回系统 tick，与 GetTickCount 做差。
#[cfg(target_os = "windows")]
#[repr(C)]
struct LastInputInfo {
    cb_size: u32,
    dw_time: u32,
}

#[cfg(target_os = "windows")]
#[link(name = "kernel32")]
extern "system" {
    fn GetTickCount() -> u32;
}

#[cfg(target_os = "windows")]
#[link(name = "user32")]
extern "system" {
    fn GetLastInputInfo(plii: *mut LastInputInfo) -> i32;
}

#[cfg(target_os = "windows")]
fn system_idle_seconds_impl() -> f64 {
    let mut info = LastInputInfo {
        cb_size: std::mem::size_of::<LastInputInfo>() as u32,
        dw_time: 0,
    };
    let ok = unsafe { GetLastInputInfo(&mut info) };
    if ok == 0 {
        return 0.0;
    }
    let now = unsafe { GetTickCount() };
    (now.wrapping_sub(info.dw_time) as f64) / 1000.0
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn primary_mouse_down() -> bool {
    false
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn system_idle_seconds_impl() -> f64 {
    0.0
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkArea {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

impl WorkArea {
    fn right(self) -> i64 {
        self.x as i64 + self.width as i64
    }

    fn bottom(self) -> i64 {
        self.y as i64 + self.height as i64
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WidgetPosition {
    pub x: i32,
    pub y: i32,
}

/// 贴边隐藏时窗口保留在屏幕内的逻辑像素数，按吸附到哪条屏幕边区分：
/// `when_left` / `when_right` 是吸附到屏幕左 / 右边缘时保留的宽度，
/// `when_top` / `when_bottom` 是吸附到屏幕上 / 下边缘时保留的高度。
/// 由前端根据立绘的内容包围盒推算后回传，避免针对某一版素材硬编码
/// （旧常量假设立绘左侧有大片透明区，换素材或改缩放大小时切割位置就会错位）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VisibleEdges {
    pub when_left: i32,
    pub when_right: i32,
    pub when_top: i32,
    pub when_bottom: i32,
}

impl Default for VisibleEdges {
    fn default() -> Self {
        // 前端尚未回传时的兜底值，等价于旧版常量。
        Self {
            when_left: 128,
            when_right: 232,
            when_top: 176,
            when_bottom: 176,
        }
    }
}

impl VisibleEdges {
    fn sanitized(self) -> Self {
        let clamp = |value: i32| value.clamp(0, 4096);
        Self {
            when_left: clamp(self.when_left),
            when_right: clamp(self.when_right),
            when_top: clamp(self.when_top),
            when_bottom: clamp(self.when_bottom),
        }
    }
}

/// 前端回传的“角色可交互矩形”，窗口逻辑坐标（CSS px）。
/// 光标落在它之外时，隐藏态的挂件不再拦截鼠标点击。
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InteractiveArea {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PositionMode {
    Preserve,
    ClampInside,
    SnapToEdge,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct WidgetPreferences {
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub monitor: Option<String>,
    pub auto_hide: bool,
    pub scale: f64,
    /// 前端按当前素材算出的贴边保留量；缺失时用 VisibleEdges::default()。
    pub visible_edges: VisibleEdges,
    /// 吸附在屏幕上边缘且当前平台不允许窗口越过工作区顶部时为 `Some("top")`，
    /// 前端据此把角色在窗口内上移，做出与其它三边一致的隐藏效果。
    pub hidden_edge: Option<String>,
}

impl Default for WidgetPreferences {
    fn default() -> Self {
        Self {
            x: None,
            y: None,
            monitor: None,
            auto_hide: true,
            scale: 1.0,
            visible_edges: VisibleEdges::default(),
            hidden_edge: None,
        }
    }
}

impl WidgetPreferences {
    fn normalized(mut self) -> Self {
        self.scale = normalize_scale(self.scale);
        self
    }
}

pub struct WidgetRuntimeState {
    move_tx: Sender<()>,
    dragging: Arc<AtomicBool>,
    #[cfg(target_os = "windows")]
    interactive: Arc<Mutex<Option<InteractiveArea>>>,
}

impl WidgetRuntimeState {
    pub fn new(app: AppHandle) -> Self {
        let (move_tx, move_rx) = mpsc::channel();
        let dragging = Arc::new(AtomicBool::new(false));
        let worker_dragging = Arc::clone(&dragging);
        let settle_app = app.clone();
        thread::spawn(move || settle_worker(settle_app, move_rx, worker_dragging));

        #[cfg(target_os = "windows")]
        let interactive = {
            // 穿透线程通过 app.try_state 反查本结构体，所以这里不用再克隆一份 Arc。
            thread::spawn(move || pointer_pass_through_worker(app));
            Arc::new(Mutex::new(None))
        };

        Self {
            move_tx,
            dragging,
            #[cfg(target_os = "windows")]
            interactive,
        }
    }

    #[cfg(target_os = "windows")]
    pub fn set_interactive_area(&self, area: Option<InteractiveArea>) {
        if let Ok(mut guard) = self.interactive.lock() {
            *guard = area;
        }
    }

    #[cfg(target_os = "windows")]
    fn interactive_area(&self) -> Option<InteractiveArea> {
        self.interactive.lock().ok().and_then(|guard| *guard)
    }

    pub fn begin_drag(&self) {
        self.dragging.store(true, Ordering::SeqCst);
    }

    pub fn cancel_drag(&self) {
        self.dragging.store(false, Ordering::SeqCst);
    }

    pub fn take_drag(&self) -> bool {
        self.dragging.swap(false, Ordering::SeqCst)
    }

    pub fn notify_moved(&self) {
        let _ = self.move_tx.send(());
    }
}

pub fn normalize_scale(scale: f64) -> f64 {
    if scale.is_finite() {
        scale.clamp(WIDGET_MIN_SCALE, WIDGET_MAX_SCALE)
    } else {
        1.0
    }
}

pub fn settle_position_in_work_area(
    position: WidgetPosition,
    size: PhysicalSize<u32>,
    area: WorkArea,
    auto_hide: bool,
    scale_factor: f64,
    visible: VisibleEdges,
) -> WidgetPosition {
    let width = size.width as i64;
    let height = size.height as i64;
    let max_x = (area.right() - width).max(area.x as i64);
    let max_y = (area.bottom() - height).max(area.y as i64);
    let clamped_x = (position.x as i64).clamp(area.x as i64, max_x);
    let clamped_y = (position.y as i64).clamp(area.y as i64, max_y);

    if !auto_hide {
        return WidgetPosition {
            x: clamped_x as i32,
            y: clamped_y as i32,
        };
    }

    let distances = [
        ((position.x as i64 - area.x as i64).max(0), 0_u8),
        ((area.right() - position.x as i64 - width).max(0), 1_u8),
        ((position.y as i64 - area.y as i64).max(0), 2_u8),
        ((area.bottom() - position.y as i64 - height).max(0), 3_u8),
    ];
    let (distance, edge) = distances
        .into_iter()
        .min_by_key(|candidate| candidate.0)
        .expect("edge list is not empty");

    let edge_trigger = (WIDGET_EDGE_TRIGGER as f64 * scale_factor).round() as i64;
    if distance > edge_trigger {
        return WidgetPosition {
            x: clamped_x as i32,
            y: clamped_y as i32,
        };
    }

    let to_physical = |value: i32| ((value as f64) * scale_factor).round() as i64;
    let visible_left = to_physical(visible.when_left).min(width);
    let visible_right = to_physical(visible.when_right).min(width);
    let visible_top = to_physical(visible.when_top).min(height);
    let visible_bottom = to_physical(visible.when_bottom).min(height);
    let mut x = clamped_x;
    let mut y = clamped_y;
    match edge {
        0 => x = area.x as i64 - width + visible_left,
        1 => x = area.right() - visible_right,
        2 => y = area.y as i64 - height + visible_top,
        3 => y = area.bottom() - visible_bottom,
        _ => unreachable!("edge index is bounded"),
    }

    if edge < 2 {
        y = clamped_y;
    } else {
        x = clamped_x;
    }

    WidgetPosition {
        x: x as i32,
        y: y as i32,
    }
}

fn preserve_position_in_work_area(
    position: WidgetPosition,
    size: PhysicalSize<u32>,
    area: WorkArea,
    scale_factor: f64,
    visible: VisibleEdges,
) -> WidgetPosition {
    let width = size.width as i64;
    let height = size.height as i64;
    let to_physical = |value: i32| ((value as f64) * scale_factor).round() as i64;
    let visible_left = to_physical(visible.when_left).min(width);
    let visible_right = to_physical(visible.when_right).min(width);
    let visible_top = to_physical(visible.when_top).min(height);
    let visible_bottom = to_physical(visible.when_bottom).min(height);
    let min_x = area.x as i64 - width + visible_left;
    let max_x = area.right() - visible_right;
    let min_y = area.y as i64 - height + visible_top;
    let max_y = area.bottom() - visible_bottom;
    WidgetPosition {
        x: (position.x as i64).clamp(min_x.min(max_x), max_x) as i32,
        y: (position.y as i64).clamp(min_y.min(max_y), max_y) as i32,
    }
}

/// macOS 的窗口服务器不允许窗口顶边越过工作区顶部（菜单栏），
/// 把窗口挪出屏幕上方的做法会被夹回工作区顶 —— 贴到上边缘就等于完全不隐藏。
/// 这里把位置收回工作区顶部，并把「上边缘隐藏」交给前端在窗口内上移角色实现；
/// 其它平台窗口可以正常挪出屏幕上方，行为保持不变。
#[cfg(target_os = "macos")]
const PLATFORM_CLAMPS_WINDOW_TOP: bool = true;
#[cfg(not(target_os = "macos"))]
const PLATFORM_CLAMPS_WINDOW_TOP: bool = false;

/// 返回实际要设置的位置，以及是否需要前端做「上边缘探出」处理。
fn clamp_top_peek(
    settled: WidgetPosition,
    area: WorkArea,
    platform_clamps_top: bool,
) -> (WidgetPosition, bool) {
    if !platform_clamps_top || settled.y >= area.y {
        return (settled, false);
    }
    (
        WidgetPosition {
            x: settled.x,
            y: area.y,
        },
        true,
    )
}

#[tauri::command]
pub fn get_widget_preferences(app: AppHandle) -> Result<WidgetPreferences, String> {
    Ok(load_preferences(&app))
}

#[tauri::command]
pub fn set_widget_auto_hide(app: AppHandle, auto_hide: bool) -> Result<WidgetPreferences, String> {
    let mut preferences = load_preferences(&app);
    preferences.auto_hide = auto_hide;
    if !auto_hide {
        settle_current_widget_position(&app, PositionMode::ClampInside, &mut preferences)?;
    }
    save_preferences(&app, &preferences)?;
    Ok(preferences)
}

#[tauri::command]
pub fn set_widget_scale(app: AppHandle, scale: f64) -> Result<WidgetPreferences, String> {
    let mut preferences = load_preferences(&app);
    preferences.scale = normalize_scale(scale);
    save_preferences(&app, &preferences)?;
    Ok(preferences)
}

#[tauri::command]
pub fn set_widget_visible_edges(
    app: AppHandle,
    edges: VisibleEdges,
) -> Result<WidgetPreferences, String> {
    let mut preferences = load_preferences(&app);
    preferences.visible_edges = edges.sanitized();
    // 立刻按新的保留量重新收边，否则要等下一次拖动才生效。
    let mode = if preferences.auto_hide {
        PositionMode::Preserve
    } else {
        PositionMode::ClampInside
    };
    settle_current_widget_position(&app, mode, &mut preferences)?;
    save_preferences(&app, &preferences)?;
    Ok(preferences)
}

/// 前端把「角色/右键菜单当前占据的矩形」报上来，供 Windows 下的鼠标穿透判定使用。
#[tauri::command]
pub fn set_widget_interactive_area(
    app: AppHandle,
    area: Option<InteractiveArea>,
) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let state = app
            .try_state::<WidgetRuntimeState>()
            .ok_or_else(|| "挂件运行状态不可用".to_string())?;
        state.set_interactive_area(area);
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (app, area);
    }
    Ok(())
}

#[tauri::command]
pub fn start_widget_drag(app: AppHandle) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    state.begin_drag();
    if let Err(error) = widget_window(&app)?.start_dragging() {
        state.cancel_drag();
        return Err(format!("开始拖动挂件失败: {error}"));
    }
    Ok(())
}

#[tauri::command]
pub fn cancel_widget_drag(app: AppHandle) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    state.cancel_drag();
    Ok(())
}

#[tauri::command]
pub fn finish_widget_drag(app: AppHandle) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    if primary_mouse_down() {
        return Ok(());
    }
    if state.take_drag() {
        settle_and_emit(&app)?;
    }
    Ok(())
}

#[tauri::command]
pub fn system_idle_seconds() -> f64 {
    system_idle_seconds_impl()
}

#[tauri::command]
pub fn resize_widget_height(app: AppHandle, height: u32) -> Result<(), String> {
    let window = widget_window(&app)?;
    let old_size = window
        .inner_size()
        .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
    let old_position = window
        .outer_position()
        .map_err(|error| format!("读取挂件位置失败: {error}"))?;
    let scale_factor = window
        .scale_factor()
        .map_err(|error| format!("读取显示器缩放失败: {error}"))?;
    let logical_width = old_size.width as f64 / scale_factor;

    window
        .set_size(LogicalSize::new(logical_width, height as f64))
        .map_err(|error| format!("调整挂件尺寸失败: {error}"))?;

    let new_size = window
        .inner_size()
        .map_err(|error| format!("读取新挂件尺寸失败: {error}"))?;
    let old_bottom = old_position.y as i64 + old_size.height as i64;
    let next_position = WidgetPosition {
        x: old_position.x,
        y: (old_bottom - new_size.height as i64) as i32,
    };
    let mut preferences = load_preferences(&app);
    let mode = if preferences.auto_hide {
        PositionMode::Preserve
    } else {
        PositionMode::ClampInside
    };
    apply_position(&window, next_position, mode, &mut preferences)?;
    save_preferences(&app, &preferences)
}

pub fn restore_widget_position(app: &AppHandle) -> Result<(), String> {
    let window = widget_window(app)?;
    let size = window
        .inner_size()
        .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
    let mut preferences = load_preferences(app);
    let saved = match (preferences.x, preferences.y) {
        (Some(x), Some(y)) => WidgetPosition { x, y },
        _ => default_position(&window, size)?,
    };
    let mode = if preferences.auto_hide {
        PositionMode::Preserve
    } else {
        PositionMode::ClampInside
    };
    apply_position(&window, saved, mode, &mut preferences)?;
    save_preferences(app, &preferences)
}

fn settle_worker(app: AppHandle, move_rx: Receiver<()>, dragging: Arc<AtomicBool>) {
    while move_rx.recv().is_ok() {
        loop {
            match move_rx.recv_timeout(WIDGET_DRAG_SETTLE_DELAY) {
                Ok(()) => continue,
                Err(RecvTimeoutError::Timeout) => break,
                Err(RecvTimeoutError::Disconnected) => return,
            }
        }
        while dragging.load(Ordering::SeqCst) && primary_mouse_down() {
            thread::sleep(Duration::from_millis(50));
        }
        if dragging.swap(false, Ordering::SeqCst) {
            if let Err(error) = settle_and_emit(&app) {
                eprintln!("DeskMate widget settle failed: {error}");
            }
        }
    }
}

/// 贴边隐藏后，窗口里那块透明区域照样会吃掉鼠标点击 —— Windows 上窗口既没有
/// WS_EX_TRANSPARENT 也没有 WS_EX_LAYERED。这里轮询系统光标位置：光标不在
/// 角色/右键菜单矩形内时把整窗设为点击穿透，移回来立刻恢复。
#[cfg(target_os = "windows")]
fn pointer_pass_through_worker(app: AppHandle) {
    let mut ignoring = false;
    loop {
        thread::sleep(WIDGET_POINTER_POLL_INTERVAL);
        let Some(window) = app.get_webview_window(WIDGET_LABEL) else {
            continue;
        };
        let wanted = WIDGET_POINTER_PASS_THROUGH && should_ignore_cursor(&app, &window);
        if wanted != ignoring && window.set_ignore_cursor_events(wanted).is_ok() {
            ignoring = wanted;
        }
    }
}

#[cfg(target_os = "windows")]
fn should_ignore_cursor(app: &AppHandle, window: &tauri::WebviewWindow) -> bool {
    // 只有「自动隐藏开着」且「窗口确实被屏幕切掉一块」时才接管，正常态一律不干预。
    if !load_preferences(app).auto_hide {
        return false;
    }
    let Some(state) = app.try_state::<WidgetRuntimeState>() else {
        return false;
    };
    let Some(rect) = state.interactive_area() else {
        return false;
    };
    let (Ok(position), Ok(size), Ok(scale_factor)) = (
        window.outer_position(),
        window.outer_size(),
        window.scale_factor(),
    ) else {
        return false;
    };
    let Ok((area, _)) = monitor_for_position(
        window,
        WidgetPosition {
            x: position.x,
            y: position.y,
        },
        size,
    ) else {
        return false;
    };
    let cut = position.x < area.x
        || position.x as i64 + size.width as i64 > area.right()
        || position.y < area.y
        || position.y as i64 + size.height as i64 > area.bottom();
    if !cut {
        return false;
    }
    let mut cursor = ScreenPoint::default();
    if unsafe { GetCursorPos(&mut cursor) } == 0 {
        return false;
    }
    let margin = WIDGET_POINTER_GRAB_MARGIN * scale_factor;
    let left = position.x as f64 + rect.x * scale_factor - margin;
    let top = position.y as f64 + rect.y * scale_factor - margin;
    let right = position.x as f64 + (rect.x + rect.width) * scale_factor + margin;
    let bottom = position.y as f64 + (rect.y + rect.height) * scale_factor + margin;
    let inside = cursor.x as f64 >= left
        && cursor.x as f64 <= right
        && cursor.y as f64 >= top
        && cursor.y as f64 <= bottom;
    !inside
}

fn settle_and_emit(app: &AppHandle) -> Result<(), String> {
    let mut preferences = load_preferences(app);
    let mode = if preferences.auto_hide {
        PositionMode::SnapToEdge
    } else {
        PositionMode::ClampInside
    };
    settle_current_widget_position(app, mode, &mut preferences)?;
    save_preferences(app, &preferences)?;
    widget_window(app)?
        .emit("widget-drag-settled", preferences)
        .map_err(|error| format!("发送挂件拖拽完成事件失败: {error}"))
}

fn settle_current_widget_position(
    app: &AppHandle,
    mode: PositionMode,
    preferences: &mut WidgetPreferences,
) -> Result<(), String> {
    let window = widget_window(app)?;
    let position = window
        .outer_position()
        .map_err(|error| format!("读取挂件位置失败: {error}"))?;
    apply_position(
        &window,
        WidgetPosition {
            x: position.x,
            y: position.y,
        },
        mode,
        preferences,
    )
}

fn apply_position(
    window: &tauri::WebviewWindow,
    position: WidgetPosition,
    mode: PositionMode,
    preferences: &mut WidgetPreferences,
) -> Result<(), String> {
    let size = window
        .inner_size()
        .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
    let (area, monitor_name) = monitor_for_position(window, position, size)?;
    let scale_factor = window
        .scale_factor()
        .map_err(|error| format!("读取显示器缩放失败: {error}"))?;
    let visible = preferences.visible_edges;
    let settled = match mode {
        PositionMode::Preserve => {
            preserve_position_in_work_area(position, size, area, scale_factor, visible)
        }
        PositionMode::ClampInside => {
            settle_position_in_work_area(position, size, area, false, scale_factor, visible)
        }
        PositionMode::SnapToEdge => {
            settle_position_in_work_area(position, size, area, true, scale_factor, visible)
        }
    };
    let (target, top_peek) = clamp_top_peek(settled, area, PLATFORM_CLAMPS_WINDOW_TOP);
    window
        .set_position(PhysicalPosition::new(target.x, target.y))
        .map_err(|error| format!("移动挂件失败: {error}"))?;
    schedule_position_retry(window, PhysicalPosition::new(target.x, target.y));
    preferences.x = Some(target.x);
    preferences.y = Some(target.y);
    preferences.monitor = monitor_name;
    preferences.hidden_edge = if top_peek {
        Some("top".to_string())
    } else {
        None
    };
    Ok(())
}

/// macOS 上原生拖拽刚结束时，窗口服务器会把窗口再摆一次（把窗口夹回屏幕内），
/// 这一下会盖掉我们刚设好的贴边位置，表现成「松手后弹回原位」。
/// 这里异步校验并补设：位置已经对了、或用户又开始拖了，就立刻收手。
fn schedule_position_retry(window: &tauri::WebviewWindow, target: PhysicalPosition<i32>) {
    let window = window.clone();
    thread::spawn(move || {
        // 每 150ms 校验一次、最多 3 秒：位置一旦对上就立刻退出，
        // 正常情况下只会跑 1~2 轮；给窗口服务器慢的机器留足余量。
        for _ in 0..20 {
            thread::sleep(Duration::from_millis(150));
            if let Some(state) = window.app_handle().try_state::<WidgetRuntimeState>() {
                if state.dragging.load(Ordering::SeqCst) {
                    return;
                }
            }
            match window.outer_position() {
                Ok(current) if current.x == target.x && current.y == target.y => return,
                Ok(_) => {
                    let _ = window.set_position(target);
                }
                Err(_) => return,
            }
        }
    });
}

fn default_position(
    window: &tauri::WebviewWindow,
    size: PhysicalSize<u32>,
) -> Result<WidgetPosition, String> {
    let monitor = window
        .primary_monitor()
        .map_err(|error| format!("读取主显示器失败: {error}"))?
        .or_else(|| window.current_monitor().ok().flatten())
        .ok_or_else(|| "无法识别显示器".to_string())?;
    let area = work_area(&monitor);
    let scale_factor = window
        .scale_factor()
        .map_err(|error| format!("读取显示器缩放失败: {error}"))?;
    let margin = (WIDGET_EDGE_MARGIN as f64 * scale_factor).round() as i32;
    Ok(WidgetPosition {
        x: area.right() as i32 - size.width as i32 - margin,
        y: area.bottom() as i32 - size.height as i32 - margin,
    })
}

fn monitor_for_position(
    window: &tauri::WebviewWindow,
    position: WidgetPosition,
    size: PhysicalSize<u32>,
) -> Result<(WorkArea, Option<String>), String> {
    let monitors = window
        .available_monitors()
        .map_err(|error| format!("读取显示器列表失败: {error}"))?;
    let mut best: Option<(u64, WorkArea, Option<String>)> = None;
    for monitor in &monitors {
        let area = work_area(monitor);
        let overlap = intersection_area(position, size, area);
        if overlap == 0 {
            continue;
        }
        let keep = best
            .as_ref()
            .map(|(best_overlap, _, _)| overlap > *best_overlap)
            .unwrap_or(true);
        if keep {
            best = Some((overlap, area, monitor.name().cloned()));
        }
    }
    if let Some((_, area, name)) = best {
        return Ok((area, name));
    }
    let monitor = window
        .current_monitor()
        .map_err(|error| format!("读取当前显示器失败: {error}"))?
        .ok_or_else(|| "无法识别显示器".to_string())?;
    Ok((work_area(&monitor), monitor.name().cloned()))
}

fn intersection_area(position: WidgetPosition, size: PhysicalSize<u32>, area: WorkArea) -> u64 {
    let left = (position.x as i64).max(area.x as i64);
    let right = (position.x as i64 + size.width as i64).min(area.right());
    let top = (position.y as i64).max(area.y as i64);
    let bottom = (position.y as i64 + size.height as i64).min(area.bottom());
    if right <= left || bottom <= top {
        return 0;
    }
    (right - left) as u64 * (bottom - top) as u64
}

fn work_area(monitor: &tauri::Monitor) -> WorkArea {
    let area = monitor.work_area();
    WorkArea {
        x: area.position.x,
        y: area.position.y,
        width: area.size.width,
        height: area.size.height,
    }
}

fn widget_window(app: &AppHandle) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window(WIDGET_LABEL)
        .ok_or_else(|| "找不到挂件窗口".to_string())
}

fn preferences_path(app: &AppHandle) -> Result<PathBuf, String> {
    let directory = app
        .path()
        .app_config_dir()
        .map_err(|error| format!("无法定位挂件配置目录: {error}"))?;
    Ok(directory.join(WIDGET_PREFERENCES_FILE))
}

fn load_preferences(app: &AppHandle) -> WidgetPreferences {
    let Ok(path) = preferences_path(app) else {
        return WidgetPreferences::default();
    };
    let Ok(json) = fs::read_to_string(path) else {
        return WidgetPreferences::default();
    };
    serde_json::from_str::<WidgetPreferences>(&json)
        .unwrap_or_default()
        .normalized()
}

fn save_preferences(app: &AppHandle, preferences: &WidgetPreferences) -> Result<(), String> {
    let path = preferences_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("创建挂件配置目录失败: {error}"))?;
    }
    let json = serde_json::to_string_pretty(preferences)
        .map_err(|error| format!("序列化挂件配置失败: {error}"))?;
    fs::write(path, json).map_err(|error| format!("保存挂件配置失败: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const AREA: WorkArea = WorkArea {
        x: 0,
        y: 0,
        width: 1920,
        height: 1080,
    };
    const SIZE: PhysicalSize<u32> = PhysicalSize::new(430, 480);

    #[test]
    fn clamps_inside_when_auto_hide_is_disabled() {
        let result = settle_position_in_work_area(
            WidgetPosition { x: 1900, y: 1060 },
            SIZE,
            AREA,
            false,
            1.0,
            VisibleEdges::default(),
        );
        assert_eq!(result, WidgetPosition { x: 1490, y: 600 });
    }

    #[test]
    fn hides_at_each_edge_but_keeps_visible_pixels() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 20, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            WidgetPosition { x: -302, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 1640, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 1688, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 20 }, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 300, y: -304 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 780 }, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 300, y: 904 }
        );
    }

    #[test]
    fn leaves_center_positions_unchanged() {
        let position = WidgetPosition { x: 600, y: 400 };
        assert_eq!(
            settle_position_in_work_area(position, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            position
        );
    }

    #[test]
    fn snaps_only_the_dominant_edge_at_a_corner() {
        let result =
            settle_position_in_work_area(WidgetPosition { x: 20, y: 10 }, SIZE, AREA, true, 1.0, VisibleEdges::default());
        assert_eq!(result, WidgetPosition { x: 20, y: -304 });
    }

    #[test]
    fn snaps_when_drag_crosses_an_edge() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 2000, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 1688, y: 300 }
        );
    }

    #[test]
    fn converts_logical_edge_metrics_for_retina_displays() {
        let size = PhysicalSize::new(560, 608);
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition {
                    x: 20_000,
                    y: 1_000
                },
                size,
                WorkArea {
                    x: 0,
                    y: 0,
                    width: 3840,
                    height: 2160,
                },
                true,
                2.0,
                VisibleEdges::default(),
            ),
            WidgetPosition { x: 3376, y: 1000 }
        );
    }

    #[test]
    fn preserves_saved_offscreen_position_but_keeps_it_reachable() {
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 1688, y: 600 }, SIZE, AREA, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 1688, y: 600 }
        );
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 5000, y: -5000 }, SIZE, AREA, 1.0, VisibleEdges::default()),
            WidgetPosition { x: 1688, y: -304 }
        );
    }

    #[test]
    fn normalizes_scale_to_safe_bounds() {
        assert_eq!(normalize_scale(0.2), 0.75);
        assert_eq!(normalize_scale(4.0), 1.15);
        assert_eq!(normalize_scale(f64::NAN), 1.0);
    }

    #[test]
    fn keeps_the_requested_amount_visible_at_each_edge() {
        // 前端按内容包围盒回传的保留量互不相等，用来锁住「每条边保留多少」的语义。
        let visible = VisibleEdges {
            when_left: 200,
            when_right: 120,
            when_top: 90,
            when_bottom: 150,
        };
        // 吸附左边缘：保留窗口最右侧 200px
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 10, y: 300 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: -230, y: 300 }
        );
        // 吸附右边缘：保留窗口最左侧 120px
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 1900, y: 300 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 1800, y: 300 }
        );
        // 吸附上边缘：保留窗口最下侧 90px
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 600, y: 10 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 600, y: -390 }
        );
        // 吸附下边缘：保留窗口最上侧 150px
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 600, y: 1000 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 600, y: 930 }
        );
        // 保存位置时同样不能用小于保留量的范围把窗口推回屏幕里
        assert_eq!(
            preserve_position_in_work_area(
                WidgetPosition { x: -230, y: 930 },
                SIZE,
                AREA,
                1.0,
                visible
            ),
            WidgetPosition { x: -230, y: 930 }
        );
    }

    #[test]
    fn clamps_oversized_visible_edges_to_the_window() {
        // 前端算出的保留量大于窗口尺寸时，不能让窗口被推成负方向。
        let visible = VisibleEdges {
            when_left: 9_999,
            when_right: 9_999,
            when_top: 9_999,
            when_bottom: 9_999,
        };
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 10, y: 300 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 0, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 1900, y: 300 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 1490, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 600, y: 10 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 600, y: 0 }
        );
        assert_eq!(
            settle_position_in_work_area(
                WidgetPosition { x: 600, y: 1000 },
                SIZE,
                AREA,
                true,
                1.0,
                visible
            ),
            WidgetPosition { x: 600, y: 600 }
        );
    }

    #[test]
    fn sanitizes_front_end_visible_edges() {
        let sanitized = VisibleEdges {
            when_left: -5,
            when_right: 99_999,
            when_top: 0,
            when_bottom: 64,
        }
        .sanitized();
        assert_eq!(
            sanitized,
            VisibleEdges {
                when_left: 0,
                when_right: 4096,
                when_top: 0,
                when_bottom: 64,
            }
        );
    }

    /// 带菜单栏的工作区：顶部不在 0，模拟真实 macOS 工作区。
    const AREA_WITH_MENUBAR: WorkArea = WorkArea {
        x: 0,
        y: 50,
        width: 3584,
        height: 1970,
    };

    #[test]
    fn top_snap_falls_back_to_peek_when_platform_clamps_window_top() {
        // settle 想把窗口推到工作区上方（y < 50），但平台不允许。
        let settled = WidgetPosition { x: 100, y: -910 };
        let (target, peek) = clamp_top_peek(settled, AREA_WITH_MENUBAR, true);
        assert_eq!(target, WidgetPosition { x: 100, y: 50 });
        assert!(peek, "上边缘被平台钳制时必须让前端做窗口内上移");
    }

    #[test]
    fn top_peek_is_not_used_where_the_window_may_leave_the_screen() {
        // Windows 允许窗口越出屏幕上方，保持原来的移窗隐藏。
        let settled = WidgetPosition { x: 100, y: -910 };
        let (target, peek) = clamp_top_peek(settled, AREA_WITH_MENUBAR, false);
        assert_eq!(target, settled);
        assert!(!peek);
    }

    #[test]
    fn other_edges_keep_their_position_untouched() {
        for settled in [
            WidgetPosition { x: -245, y: 600 },
            WidgetPosition { x: 1607, y: 600 },
            WidgetPosition { x: 300, y: 836 },
            WidgetPosition { x: 300, y: 50 },
        ] {
            let (target, peek) = clamp_top_peek(settled, AREA_WITH_MENUBAR, true);
            assert_eq!(target, settled);
            assert!(!peek);
        }
    }
}
