use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize};

pub const WIDGET_LABEL: &str = "widget";
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
    fn CGEventCreate(source: *const std::ffi::c_void) -> *mut std::ffi::c_void;
    fn CGEventGetLocation(event: *const std::ffi::c_void) -> CGPoint;
    fn CFRelease(value: *const std::ffi::c_void);
}

#[cfg(target_os = "macos")]
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
struct CGPoint {
    x: f64,
    y: f64,
}

/// Quartz 返回全局逻辑像素坐标；窗口位置在 Retina 屏上需除以 scale_factor。
#[cfg(target_os = "macos")]
fn cursor_position() -> Option<CGPoint> {
    let event = unsafe { CGEventCreate(std::ptr::null()) };
    if event.is_null() {
        return None;
    }
    let point = unsafe { CGEventGetLocation(event) };
    unsafe { CFRelease(event.cast_const()) };
    Some(point)
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

impl InteractiveArea {
    fn contains(self, x: f64, y: f64, padding: f64) -> bool {
        let right = self.x + self.width + padding;
        let bottom = self.y + self.height + padding;
        self.width > 0.0
            && self.height > 0.0
            && x >= self.x - padding
            && x <= right
            && y >= self.y - padding
            && y <= bottom
    }
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct PointerInteractiveAreas {
    revision: u64,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
    enabled: bool,
    suspend: bool,
    role: Option<InteractiveArea>,
    controls: Vec<InteractiveArea>,
}

#[cfg(target_os = "macos")]
const ANIMAL_POINTER_PADDING: f64 = 4.0;
#[cfg(target_os = "macos")]
const POINTER_PIXEL_HIT_MAX_AGE: Duration = Duration::from_millis(120);
#[cfg(target_os = "macos")]
const POINTER_PIXEL_HIT_MAX_DRIFT: f64 = 2.0;

#[cfg(target_os = "macos")]
#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
struct PointerSampleRequest {
    request_id: u64,
    revision: u64,
    x: f64,
    y: f64,
}

#[cfg(target_os = "macos")]
#[derive(Debug, Clone, Copy)]
struct PointerPixelHit {
    request_id: u64,
    revision: u64,
    x: f64,
    y: f64,
    opaque: bool,
    sampled_at: Instant,
}

#[cfg(target_os = "macos")]
#[derive(Default)]
struct PointerState {
    areas: Option<PointerInteractiveAreas>,
    hit: Option<PointerPixelHit>,
    pending: Vec<(PointerSampleRequest, Instant)>,
    revision: u64,
    resizing: bool,
    require_viewport: bool,
}

#[cfg(target_os = "macos")]
impl PointerState {
    fn invalidate(&mut self, resizing: bool) {
        self.resizing = resizing;
        self.require_viewport = true;
        self.areas = None;
        self.hit = None;
        self.pending.clear();
    }

    fn set_areas(&mut self, areas: Option<PointerInteractiveAreas>, width: f64, height: f64) {
        let Some(areas) = areas else {
            self.areas = None;
            self.hit = None;
            self.pending.clear();
            return;
        };
        if areas.revision <= self.revision {
            return;
        }
        self.revision = areas.revision;
        self.areas = None;
        self.hit = None;
        self.pending.clear();
        let matches = |reported: Option<f64>, actual: f64| reported
            .map_or(!self.require_viewport, |value| value.is_finite() && (value - actual).abs() <= 1.0);
        if self.resizing || !matches(areas.viewport_width, width) || !matches(areas.viewport_height, height) {
            return;
        }
        self.areas = Some(areas);
    }

    fn accept_hit(&mut self, request_id: u64, revision: u64, x: f64, y: f64, opaque: bool, now: Instant) {
        let Some(index) = self.pending.iter().position(|(request, _)| request.request_id == request_id) else {
            return;
        };
        let (request, sent_at) = self.pending.remove(index);
        if self.resizing || self.areas.as_ref().map(|areas| areas.revision) != Some(revision)
            || request.revision != revision
            || !now.checked_duration_since(sent_at).is_some_and(|age| age <= POINTER_PIXEL_HIT_MAX_AGE)
            || (request.x - x).abs() > POINTER_PIXEL_HIT_MAX_DRIFT
            || (request.y - y).abs() > POINTER_PIXEL_HIT_MAX_DRIFT
            || self.hit.is_some_and(|hit| hit.request_id >= request_id)
        {
            return;
        }
        self.hit = Some(PointerPixelHit { request_id, revision, x, y, opaque, sampled_at: sent_at });
    }
}

#[cfg(target_os = "macos")]
#[derive(Default)]
struct PointerGesture {
    was_down: bool,
    captured: bool,
    clickable_until: Option<Instant>,
}

#[cfg(target_os = "macos")]
impl PointerGesture {
    fn should_ignore(&mut self, base: bool, down: bool, dragging: bool, suspended: bool, over_interactive: bool, now: Instant) -> bool {
        if down && !self.was_down {
            self.captured = !base && over_interactive;
        }
        if self.captured && self.was_down && !down {
            self.clickable_until = Some(now + Duration::from_millis(500));
            self.captured = false;
        }
        self.was_down = down;
        let grace = over_interactive && self.clickable_until.is_some_and(|until| now <= until);
        !(dragging || suspended || (down && self.captured) || grace) && base
    }
}

#[cfg(target_os = "macos")]
fn should_ignore_animal_pointer(
    areas: Option<PointerInteractiveAreas>,
    cursor: Option<CGPoint>,
    window_position: PhysicalPosition<i32>,
    scale_factor: f64,
    pixel_hit: Option<PointerPixelHit>,
    now: Instant,
) -> bool {
    let (Some(areas), Some(cursor)) = (areas, cursor) else {
        return false;
    };
    if !areas.enabled || areas.suspend || scale_factor <= 0.0 {
        return false;
    }
    let x = cursor.x - window_position.x as f64 / scale_factor;
    let y = cursor.y - window_position.y as f64 / scale_factor;
    if areas.controls.iter().any(|rect| rect.contains(x, y, 0.0)) {
        return false;
    }
    let Some(role) = areas.role else {
        return false;
    };
    if !role.contains(x, y, ANIMAL_POINTER_PADDING) {
        return true;
    }
    let Some(hit) = pixel_hit else {
        return false;
    };
    let fresh = now
        .checked_duration_since(hit.sampled_at)
        .is_some_and(|age| age <= POINTER_PIXEL_HIT_MAX_AGE);
    let same_point = hit.request_id > 0 && hit.revision == areas.revision
        && (hit.x - x).abs() <= POINTER_PIXEL_HIT_MAX_DRIFT
        && (hit.y - y).abs() <= POINTER_PIXEL_HIT_MAX_DRIFT;
    fresh && same_point && !hit.opaque
}

/// 前端按素材内容包围盒实测的“角色内容矩形”，窗口逻辑坐标（CSS px）。
/// 贴边吸附的触发与落点都以它为基准：角色视觉贴边即吸附，
/// 吸附后只保留 `handle` 逻辑像素的“抓手”露在屏幕内。
/// 为空（前端尚未测量 / VRM 等）时回落到旧的窗口矩形行为。
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContentGeometry {
    pub rect: InteractiveArea,
    pub handle: i32,
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
            // 开箱默认完整显示挂件，贴边隐藏交给用户在右键菜单开启
            // （Windows 验收观察项：默认隐藏 + 边缘停靠被当成「看不到挂件」）。
            auto_hide: false,
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

/// 串行化动物移动 / settle / retry，并用 generation 阻止旧 settle 覆盖新移动。
/// 硬约束：持有 `write_lock` 的线程不得等待主事件循环（锁内窗口 API 调用必然等），
/// 因此所有可能进锁的 Tauri 命令必须是 async，让锁等待发生在 Tokio 线程，
/// 主线程保持可响应 —— 否则后台持锁线程与主线程同步进锁的命令互等成永久死锁。
struct PositionMoveGate {
    move_generation: AtomicU64,
    write_lock: Mutex<()>,
}

impl PositionMoveGate {
    fn new() -> Self {
        Self {
            move_generation: AtomicU64::new(0),
            write_lock: Mutex::new(()),
        }
    }

    fn generation(&self) -> u64 {
        self.move_generation.load(Ordering::SeqCst)
    }

    fn animal_move<T>(
        &self,
        write: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, String> {
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let result = write()?;
        self.move_generation.fetch_add(1, Ordering::SeqCst);
        Ok(result)
    }

    fn write_if_generation_current(
        &self,
        expected_generation: u64,
        write: impl FnOnce() -> Result<(), String>,
    ) -> Result<bool, String> {
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if self.generation() != expected_generation {
            return Ok(false);
        }
        write()?;
        Ok(true)
    }

    fn place_if_generation_current(
        &self,
        expected_generation: u64,
        write: impl FnOnce() -> Result<(), String>,
    ) -> Result<Option<u64>, String> {
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if self.generation() != expected_generation {
            return Ok(None);
        }
        write()?;
        let placed_generation = self.move_generation.fetch_add(1, Ordering::SeqCst) + 1;
        Ok(Some(placed_generation))
    }
}

pub struct WidgetRuntimeState {
    move_tx: Sender<()>,
    dragging: Arc<AtomicBool>,
    /// 前端实测的角色内容矩形（全平台都需要：贴边吸附以它为基准）。
    content: Mutex<Option<ContentGeometry>>,
    position_moves: PositionMoveGate,
    #[cfg(target_os = "windows")]
    interactive: Arc<Mutex<Option<InteractiveArea>>>,
    #[cfg(target_os = "macos")]
    pointer: Arc<Mutex<PointerState>>,
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
        #[cfg(target_os = "macos")]
        let pointer = {
            let pointer = Arc::new(Mutex::new(PointerState::default()));
            let worker_pointer = Arc::clone(&pointer);
            thread::spawn(move || {
                animal_pointer_pass_through_worker(app, worker_pointer)
            });
            pointer
        };

        Self {
            move_tx,
            dragging,
            content: Mutex::new(None),
            position_moves: PositionMoveGate::new(),
            #[cfg(target_os = "windows")]
            interactive,
            #[cfg(target_os = "macos")]
            pointer,
        }
    }

    pub fn animal_move_generation(&self) -> u64 {
        self.position_moves.generation()
    }

    pub fn set_content_geometry(&self, geometry: Option<ContentGeometry>) {
        if let Ok(mut guard) = self.content.lock() {
            *guard = geometry;
        }
    }

    pub fn content_geometry(&self) -> Option<ContentGeometry> {
        self.content.lock().ok().and_then(|guard| *guard)
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
    content: Option<ContentGeometry>,
) -> WidgetPosition {
    let width = size.width as i64;
    let height = size.height as i64;

    // 内容基准路径：触发与落点都按角色内容矩形计算，角色视觉贴边即吸附，
    // 吸附后仅保留 handle 宽度的“抓手”露在屏幕内，窗口跳变量恰好贴合，无瞬移感。
    if let Some(geometry) = content {
        return settle_position_by_content(position, area, auto_hide, scale_factor, geometry);
    }

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

/// 内容基准的吸附结算。`keep_axis_inside` 把另一条轴夹到“角色内容完整落在工作区内”的范围，
/// 允许窗口为了角色贴边而部分越出屏幕（非隐藏模式同样适用，角色这才真正碰得到屏幕边）。
fn settle_position_by_content(
    position: WidgetPosition,
    area: WorkArea,
    auto_hide: bool,
    scale_factor: f64,
    geometry: ContentGeometry,
) -> WidgetPosition {
    let rect = &geometry.rect;
    let to_physical = |value: f64| (value * scale_factor).round() as i64;
    let offset_x = to_physical(rect.x);
    let offset_y = to_physical(rect.y);
    let content_w = to_physical(rect.width).max(1);
    let content_h = to_physical(rect.height).max(1);
    let handle = to_physical(geometry.handle as f64).max(0);

    let keep_axis_inside = |value: i64, offset: i64, len: i64, low: i64, high: i64| -> i64 {
        let min_value = low - offset;
        let max_value = high - offset - len;
        value.clamp(min_value.min(max_value), max_value)
    };
    let inside_x = keep_axis_inside(position.x as i64, offset_x, content_w, area.x as i64, area.right());
    let inside_y = keep_axis_inside(position.y as i64, offset_y, content_h, area.y as i64, area.bottom());

    if !auto_hide {
        return WidgetPosition {
            x: inside_x as i32,
            y: inside_y as i32,
        };
    }

    let content_left = position.x as i64 + offset_x;
    let content_right = content_left + content_w;
    let content_top = position.y as i64 + offset_y;
    let content_bottom = content_top + content_h;
    let distances = [
        ((content_left - area.x as i64).max(0), 0_u8),
        ((area.right() - content_right).max(0), 1_u8),
        ((content_top - area.y as i64).max(0), 2_u8),
        ((area.bottom() - content_bottom).max(0), 3_u8),
    ];
    let (distance, edge) = distances
        .into_iter()
        .min_by_key(|candidate| candidate.0)
        .expect("edge list is not empty");

    let edge_trigger = (WIDGET_EDGE_TRIGGER as f64 * scale_factor).round() as i64;
    if distance > edge_trigger {
        return WidgetPosition {
            x: inside_x as i32,
            y: inside_y as i32,
        };
    }

    let mut x = inside_x;
    let mut y = inside_y;
    match edge {
        0 => x = area.x as i64 - handle - offset_x,
        1 => x = area.right() + handle - offset_x - content_w,
        2 => y = area.y as i64 - handle - offset_y,
        3 => y = area.bottom() + handle - offset_y - content_h,
        _ => unreachable!("edge index is bounded"),
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
    content: Option<ContentGeometry>,
) -> WidgetPosition {
    let width = size.width as i64;
    let height = size.height as i64;

    // 内容基准：位置必须仍能被用户抓回来 —— 角色至少保留 handle 宽度露在屏幕内。
    if let Some(geometry) = content {
        let rect = &geometry.rect;
        let to_physical = |value: f64| (value * scale_factor).round() as i64;
        let offset_x = to_physical(rect.x);
        let offset_y = to_physical(rect.y);
        let content_w = to_physical(rect.width).max(1);
        let content_h = to_physical(rect.height).max(1);
        let handle = to_physical(geometry.handle as f64).max(0);
        let min_x = area.x as i64 - handle - offset_x;
        let max_x = area.right() + handle - offset_x - content_w;
        let min_y = area.y as i64 - handle - offset_y;
        let max_y = area.bottom() + handle - offset_y - content_h;
        return WidgetPosition {
            x: (position.x as i64).clamp(min_x.min(max_x), max_x) as i32,
            y: (position.y as i64).clamp(min_y.min(max_y), max_y) as i32,
        };
    }

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

/// 异步命令：settle/贴边会进位置锁并等待主事件循环应答窗口 API，
/// 主线程绝不能同步进锁，否则与持锁的后台线程互等成永久死锁。
#[tauri::command]
pub async fn set_widget_auto_hide(
    app: AppHandle,
    auto_hide: bool,
) -> Result<WidgetPreferences, String> {
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

/// 异步命令：理由同 set_widget_auto_hide，主线程不进位置锁。
#[tauri::command]
pub async fn set_widget_visible_edges(
    app: AppHandle,
    edges: VisibleEdges,
) -> Result<WidgetPreferences, String> {
    let mut preferences = load_preferences(&app);
    preferences.visible_edges = edges.sanitized();
    // 只在自动隐藏开启时立刻按新保留量重新收边；关闭时绝不能动窗口位置 ——
    // 前端每 2s 随动作重测内容矩形并回传本命令，若此时 settle 会按「动画中的
    // 内容矩形」重新夹取窗口位置，静置的挂件就会随机瞬移甚至被推出屏幕。
    if preferences.auto_hide {
        settle_current_widget_position(&app, PositionMode::Preserve, &mut preferences)?;
    }
    save_preferences(&app, &preferences)?;
    Ok(preferences)
}

/// 前端把「角色内容矩形 + 抓手宽度」实测值回传，贴边吸附按角色基准结算。
#[tauri::command]
pub fn set_widget_content_rect(
    app: AppHandle,
    rect: Option<InteractiveArea>,
    handle: Option<i32>,
) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let geometry = rect.map(|value| ContentGeometry {
        rect: value,
        handle: handle.unwrap_or(64).clamp(24, 320),
    });
    state.set_content_geometry(geometry);
    Ok(())
}

/// 读取当前生效的角色内容几何信息；前端尚未测量时为 None（回落窗口基准行为）。
fn content_geometry(app: &AppHandle) -> Option<ContentGeometry> {
    app.try_state::<WidgetRuntimeState>()
        .and_then(|state| state.content_geometry())
}

/// 前端把「角色/右键菜单当前占据的矩形」报上来，供 Windows 下的鼠标穿透判定使用。
#[tauri::command]
pub fn set_widget_interactive_area(
    app: AppHandle,
    area: Option<InteractiveArea>,
    animal_areas: Option<PointerInteractiveAreas>,
) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let state = app
            .try_state::<WidgetRuntimeState>()
            .ok_or_else(|| "挂件运行状态不可用".to_string())?;
        state.set_interactive_area(area);
        // 更新窗口 region 以启用分级鼠标穿透
        if let Some(window) = app.get_webview_window(WIDGET_LABEL) {
            if let Ok(hwnd) = window.hwnd() {
                let sf = window.scale_factor().unwrap_or(1.0);
                let active = state.interactive_area();
                let rects: Vec<InteractiveArea> = active.into_iter().collect();
                unsafe { win32_hit::apply_hit_rects(hwnd.0, &rects, sf); }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = area;
    }
    #[cfg(target_os = "macos")]
    {
        let state = app
            .try_state::<WidgetRuntimeState>()
            .ok_or_else(|| "挂件运行状态不可用".to_string())?;
        let window = widget_window(&app)?;
        let size = window.inner_size().map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
        let scale = window.scale_factor().map_err(|error| format!("读取显示器缩放失败: {error}"))?;
        if let Ok(mut guard) = state.pointer.lock() {
            guard.set_areas(animal_areas, size.width as f64 / scale, size.height as f64 / scale);
        };
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = animal_areas;
    }
    Ok(())
}

#[tauri::command]
pub fn set_widget_animal_pixel_hit(
    app: AppHandle,
    request_id: u64,
    revision: u64,
    x: f64,
    y: f64,
    opaque: bool,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        if !x.is_finite() || !y.is_finite() {
            return Err("像素命中坐标无效".to_string());
        }
        let state = app
            .try_state::<WidgetRuntimeState>()
            .ok_or_else(|| "挂件运行状态不可用".to_string())?;
        let mut guard = state
            .pointer
            .lock()
            .map_err(|_| "像素命中状态不可用".to_string())?;
        guard.accept_hit(request_id, revision, x, y, opaque, Instant::now());
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (app, request_id, revision, x, y, opaque);
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

/// 异步命令：settle_and_emit 会进位置锁，主线程不进锁（理由同 set_widget_auto_hide）。
#[tauri::command]
pub async fn finish_widget_drag(app: AppHandle) -> Result<(), String> {
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

/// 动物移动系统：绕过 settle/贴边逻辑，把挂件窗口挪到绝对桌面坐标。
/// 供片 2 自由走动与片 3 抓起放下调用；不影响挂件原有定位。
/// 异步命令：animal_move 持锁期间调用窗口 API，主线程不进锁（理由同 set_widget_auto_hide）。
#[tauri::command]
pub async fn move_widget_to(app: AppHandle, x: i32, y: i32) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let window = widget_window(&app)?;
    state.position_moves.animal_move(|| {
        let size = window
            .outer_size()
            .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
        let monitors = window
            .available_monitors()
            .map_err(|error| format!("读取显示器列表失败: {error}"))?;
        let target = WidgetPosition { x, y };
        if !monitors
            .iter()
            .any(|monitor| target_fits_work_area(target, size, work_area(monitor)))
        {
            return Err("动物移动目标超出工作区".to_string());
        }
        window
            .set_position(PhysicalPosition::new(x, y))
            .map_err(|error| format!("移动挂件窗口失败: {error}"))
    })
}

/// 返回所有显示器的物理工作区（不含菜单栏/任务栏），供前端做桌面坐标并集。
#[tauri::command]
pub fn list_desktop_work_areas(
    app: AppHandle,
) -> Result<Vec<(String, i32, i32, u32, u32)>, String> {
    let window = widget_window(&app)?;
    let monitors = window
        .available_monitors()
        .map_err(|error| format!("读取显示器列表失败: {error}"))?;
    Ok(monitors
        .into_iter()
        .map(|monitor| {
            let area = work_area(&monitor);
            (
                monitor.name().cloned().unwrap_or_else(|| "unknown".to_string()),
                area.x,
                area.y,
                area.width,
                area.height,
            )
        })
        .collect())
}

/// 异步命令：animal_move 持锁期间调用窗口 API，主线程不进锁（理由同 set_widget_auto_hide）。
#[tauri::command]
pub async fn resize_widget_height(app: AppHandle, height: u32) -> Result<u32, String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let window = widget_window(&app)?;
    let (actual_height, next_position) = state.position_moves.animal_move(|| {
        let old_inner_size = window
            .inner_size()
            .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
        let old_outer_size = window
            .outer_size()
            .map_err(|error| format!("读取挂件外框尺寸失败: {error}"))?;
        let old_position = window
            .outer_position()
            .map_err(|error| format!("读取挂件位置失败: {error}"))?;
        let scale_factor = window
            .scale_factor()
            .map_err(|error| format!("读取显示器缩放失败: {error}"))?;
        let logical_width = old_inner_size.width as f64 / scale_factor;
        let frame_height_delta =
            old_outer_size.height as i64 - old_inner_size.height as i64;
        let (area, _) = monitor_for_position(&window, WidgetPosition { x: old_position.x, y: old_position.y }, old_outer_size)?;
        let height = bounded_widget_height(height, area.height, scale_factor, frame_height_delta);
        if (old_inner_size.height as f64 / scale_factor - height as f64).abs() < 0.5 {
            return Ok((height, None));
        }
        #[cfg(target_os = "macos")]
        state.pointer.lock().map_err(|_| "指针状态不可用".to_string())?.invalidate(true);
        let resized = (|| {
            window
                .set_size(LogicalSize::new(logical_width, height as f64))
                .map_err(|error| format!("调整挂件尺寸失败: {error}"))?;
            let new_outer_height = window.outer_size()
                .map_err(|error| format!("读取挂件外框尺寸失败: {error}"))?.height as i64;
            let old_bottom = old_position.y as i64 + old_outer_size.height as i64;
            let next = PhysicalPosition::new(
                old_position.x,
                (old_bottom - new_outer_height).clamp(area.y as i64, (area.bottom() - new_outer_height).max(area.y as i64)) as i32,
            );
            window
                .set_position(next)
                .map_err(|error| format!("锚定挂件右下角失败: {error}"))?;
            let actual = window.inner_size().map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
            Ok(((actual.height as f64 / scale_factor).round() as u32, Some(WidgetPosition { x: next.x, y: next.y })))
        })();
        #[cfg(target_os = "macos")]
        state.pointer.lock().map_err(|_| "指针状态不可用".to_string())?.invalidate(false);
        resized
    })?;
    let Some(next_position) = next_position else { return Ok(actual_height); };
    let mut preferences = load_preferences(&app);
    preferences.x = Some(next_position.x);
    preferences.y = Some(next_position.y);
    save_preferences(&app, &preferences)?;
    Ok(actual_height)
}

fn bounded_widget_height(requested: u32, work_height: u32, scale: f64, frame_delta: i64) -> u32 {
    let maximum = (((work_height as i64 - frame_delta).max(1) as f64 / scale).floor() as u32).clamp(1, 4096);
    requested.clamp(64.min(maximum), maximum)
}

pub fn restore_widget_position(app: &AppHandle) -> Result<(), String> {
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let expected_move_generation = state.animal_move_generation();
    let window = widget_window(app)?;
    let size = window
        .inner_size()
        .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
    let mut preferences = load_preferences(app);
    let saved = match (preferences.x, preferences.y) {
        (Some(x), Some(y)) => WidgetPosition { x, y },
        _ => default_position(&window, size)?,
    };
    // 保存的显示器名字与当前枚举不匹配（如外接屏被拔掉），回落到主屏中心。
    if let Some(ref monitor_name) = preferences.monitor {
        let current_monitors = window
            .available_monitors()
            .map_err(|error| format!("读取显示器列表失败: {error}"))?;
        let monitor_gone = !current_monitors
            .iter()
            .any(|monitor| monitor.name().as_deref() == Some(monitor_name));
        if monitor_gone {
            let fallback = default_position(&window, size)?;
            preferences.x = Some(fallback.x);
            preferences.y = Some(fallback.y);
            preferences.monitor = None;
            preferences.auto_hide = false; // 新显示器上从完整显示开始，避免不可见
            save_preferences(app, &preferences)?;
            return restore_widget_position(app); // 用回落后的位置重新进入
        }
    }
    let mode = if preferences.auto_hide {
        PositionMode::Preserve
    } else {
        PositionMode::ClampInside
    };
    apply_position(
        &window,
        Some(saved),
        mode,
        &mut preferences,
        expected_move_generation,
    )?;
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
                eprintln!("Qiling widget settle failed: {error}");
            }
        }
    }
}

/// 贴边隐藏后，透明区域不应拦截鼠标点击。用 LAYERED+LWA_ALPHA(255)+TRANSPARENT
/// 三件套做整窗穿透（set_ignore_cursor_events 单独翻转 WS_EX_TRANSPARENT 实测无效）。
#[cfg(target_os = "windows")]
fn pointer_pass_through_worker(app: AppHandle) {
    let mut ignoring = false;
    loop {
        thread::sleep(WIDGET_POINTER_POLL_INTERVAL);
        let Some(window) = app.get_webview_window(WIDGET_LABEL) else {
            continue;
        };
        if !WIDGET_POINTER_PASS_THROUGH {
            continue;
        }
        let wanted = should_ignore_cursor(&app, &window);
        if wanted == ignoring {
            continue;
        }
        if let Ok(hwnd) = window.hwnd() {
            unsafe { win32_hit::set_full_passthrough(hwnd.0, wanted); }
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

#[cfg(target_os = "macos")]
fn animal_pointer_pass_through_worker(
    app: AppHandle,
    pointer: Arc<Mutex<PointerState>>,
) {
    let mut ignoring = false;
    let mut request_id = 0_u64;
    let mut gesture = PointerGesture::default();
    loop {
        thread::sleep(Duration::from_millis(40));
        let Some(window) = app.get_webview_window(WIDGET_LABEL) else {
            continue;
        };
        let cursor = cursor_position();
        let now = Instant::now();
        let down = primary_mouse_down();
        let (areas, hit) = pointer.lock().ok().map(|guard| (guard.areas.clone(), guard.hit)).unwrap_or_default();
        let (Ok(position), Ok(scale)) = (window.outer_position(), window.scale_factor()) else { continue; };
        let mut over_interactive = false;
        let mut sample_failed = false;
        if let (Some(areas), Some(cursor)) = (
                areas.as_ref(),
                cursor,
            ) {
                if scale > 0.0 {
                    let local_x = cursor.x - position.x as f64 / scale;
                    let local_y = cursor.y - position.y as f64 / scale;
                    let over_control = areas
                        .controls
                        .iter()
                        .any(|rect| rect.contains(local_x, local_y, 0.0));
                    let in_role = areas.enabled
                        && !areas.suspend
                        && !over_control
                        && areas
                            .role
                            .is_some_and(|rect| rect.contains(local_x, local_y, ANIMAL_POINTER_PADDING));
                    over_interactive = over_control || in_role;
                    if in_role && !down {
                        request_id = request_id.saturating_add(1);
                        let request = PointerSampleRequest { request_id, revision: areas.revision, x: local_x, y: local_y };
                        let queued = if let Ok(mut guard) = pointer.lock() {
                            if !guard.resizing && guard.areas.as_ref().map(|current| current.revision) == Some(areas.revision) {
                                guard.pending.retain(|(_, sent)| now.duration_since(*sent) <= POINTER_PIXEL_HIT_MAX_AGE);
                                guard.pending.push((request, now));
                                true
                            } else { false }
                        } else { false };
                        sample_failed = !queued || window.emit("widget-pointer-sample", request).is_err();
                    }
                }
        }
        let current_geometry = pointer.lock().ok().is_some_and(|guard| !guard.resizing && guard.areas.is_some());
        let suspended = !current_geometry || areas.as_ref().is_some_and(|areas| areas.suspend);
        let dragging = app.try_state::<WidgetRuntimeState>().is_some_and(|state| state.dragging.load(Ordering::SeqCst));
        let base = should_ignore_animal_pointer(
                        areas,
                        cursor,
                        position,
                        scale,
                        if sample_failed { None } else { hit },
                        now,
                    );
        let wanted = gesture.should_ignore(base, down, dragging, suspended, over_interactive, now);
        if wanted != ignoring && window.set_ignore_cursor_events(wanted).is_ok() {
            ignoring = wanted;
        }
    }
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
    let state = app
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let expected_move_generation = state.animal_move_generation();
    let window = widget_window(app)?;
    apply_position(
        &window,
        None,
        mode,
        preferences,
        expected_move_generation,
    )
}

fn apply_position(
    window: &tauri::WebviewWindow,
    requested_position: Option<WidgetPosition>,
    mode: PositionMode,
    preferences: &mut WidgetPreferences,
    expected_move_generation: u64,
) -> Result<(), String> {
    let state = window
        .app_handle()
        .try_state::<WidgetRuntimeState>()
        .ok_or_else(|| "挂件运行状态不可用".to_string())?;
    let mut placement = None;
    let scheduled_generation = state.position_moves.place_if_generation_current(
        expected_move_generation,
        || {
            let position = match requested_position {
                Some(position) => position,
                None => {
                    let current = window
                        .outer_position()
                        .map_err(|error| format!("读取挂件位置失败: {error}"))?;
                    WidgetPosition {
                        x: current.x,
                        y: current.y,
                    }
                }
            };
            let size = window
                .inner_size()
                .map_err(|error| format!("读取挂件尺寸失败: {error}"))?;
            let (area, monitor_name) = monitor_for_position(window, position, size)?;
            let scale_factor = window
                .scale_factor()
                .map_err(|error| format!("读取显示器缩放失败: {error}"))?;
            let visible = preferences.visible_edges;
            let settled = match mode {
                PositionMode::Preserve => preserve_position_in_work_area(
                    position,
                    size,
                    area,
                    scale_factor,
                    visible,
                    content_geometry(window.app_handle()),
                ),
                PositionMode::ClampInside => settle_position_in_work_area(
                    position,
                    size,
                    area,
                    false,
                    scale_factor,
                    visible,
                    content_geometry(window.app_handle()),
                ),
                PositionMode::SnapToEdge => settle_position_in_work_area(
                    position,
                    size,
                    area,
                    true,
                    scale_factor,
                    visible,
                    content_geometry(window.app_handle()),
                ),
            };
            let (target, top_peek) =
                clamp_top_peek(settled, area, PLATFORM_CLAMPS_WINDOW_TOP);
            window
                .set_position(PhysicalPosition::new(target.x, target.y))
                .map_err(|error| format!("移动挂件失败: {error}"))?;
            placement = Some((target, monitor_name, top_peek));
            Ok(())
        },
    )?;
    let Some((target, monitor_name, top_peek)) = placement else {
        return Ok(());
    };
    let Some(scheduled_generation) = scheduled_generation else {
        return Ok(());
    };
    schedule_position_retry(
        window,
        PhysicalPosition::new(target.x, target.y),
        scheduled_generation,
    );
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
fn schedule_position_retry(
    window: &tauri::WebviewWindow,
    target: PhysicalPosition<i32>,
    scheduled_move_generation: u64,
) {
    let window = window.clone();
    thread::spawn(move || {
        // 每 150ms 校验一次、最多 3 秒：位置一旦对上就立刻退出，
        // 正常情况下只会跑 1~2 轮；给窗口服务器慢的机器留足余量。
        for _ in 0..20 {
            thread::sleep(Duration::from_millis(150));
            let Some(state) = window.app_handle().try_state::<WidgetRuntimeState>() else {
                return;
            };
            if state.dragging.load(Ordering::SeqCst) {
                return;
            }
            let result = state.position_moves.write_if_generation_current(
                scheduled_move_generation,
                || match window.outer_position() {
                    Ok(current) if current.x == target.x && current.y == target.y => Ok(()),
                    Ok(_) => window
                        .set_position(target)
                        .map_err(|error| format!("重试移动挂件失败: {error}")),
                    Err(error) => Err(format!("读取挂件位置失败: {error}")),
                },
            );
            match result {
                Ok(true) => {}
                Ok(false) | Err(_) => return,
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

fn target_fits_work_area(
    position: WidgetPosition,
    size: PhysicalSize<u32>,
    area: WorkArea,
) -> bool {
    position.x >= area.x
        && position.y >= area.y
        && position.x as i64 + size.width as i64 <= area.right()
        && position.y as i64 + size.height as i64 <= area.bottom()
}

#[cfg(test)]
fn resized_outer_height(
    requested_logical_height: u32,
    scale_factor: f64,
    frame_height_delta: i64,
) -> i64 {
    (requested_logical_height as f64 * scale_factor).round() as i64 + frame_height_delta
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
    fn failed_animal_move_does_not_cancel_position_retry() {
        let gate = PositionMoveGate::new();
        assert!(gate
            .animal_move(|| Err::<(), _>("write failed".to_string()))
            .is_err());

        let retried = AtomicBool::new(false);
        let wrote = gate
            .write_if_generation_current(0, || {
                retried.store(true, Ordering::SeqCst);
                Ok(())
            })
            .unwrap();
        assert!(wrote);
        assert!(retried.load(Ordering::SeqCst));
    }

    #[test]
    fn animal_move_target_must_stay_inside_work_area() {
        let inside = target_fits_work_area(WidgetPosition { x: 100, y: 100 }, SIZE, AREA);
        let outside = target_fits_work_area(WidgetPosition { x: 1800, y: 100 }, SIZE, AREA);
        assert!(inside);
        assert!(!outside);
    }

    #[test]
    fn animal_move_cannot_interleave_with_retry_write() {
        let gate = Arc::new(PositionMoveGate::new());
        let position = Arc::new(Mutex::new(0));
        let (retry_started_tx, retry_started_rx) = mpsc::channel();
        let (release_retry_tx, release_retry_rx) = mpsc::channel();

        let retry_gate = Arc::clone(&gate);
        let retry_position = Arc::clone(&position);
        let retry = thread::spawn(move || {
            retry_gate.write_if_generation_current(0, || {
                retry_started_tx.send(()).unwrap();
                release_retry_rx.recv().unwrap();
                *retry_position.lock().unwrap() = -1;
                Ok(())
            })
        });
        retry_started_rx.recv().unwrap();

        let (animal_started_tx, animal_started_rx) = mpsc::channel();
        let animal_gate = Arc::clone(&gate);
        let animal_position = Arc::clone(&position);
        let animal = thread::spawn(move || {
            animal_gate.animal_move(|| {
                animal_started_tx.send(()).unwrap();
                *animal_position.lock().unwrap() = 2;
                Ok(())
            })
        });

        assert!(animal_started_rx
            .recv_timeout(Duration::from_millis(100))
            .is_err());
        release_retry_tx.send(()).unwrap();
        assert!(retry.join().unwrap().unwrap());
        animal.join().unwrap().unwrap();
        assert_eq!(*position.lock().unwrap(), 2);
    }

    #[test]
    fn stale_settle_does_not_overwrite_new_animal_move() {
        let gate = PositionMoveGate::new();
        let expected_generation = gate.generation();
        let position = Arc::new(Mutex::new(0));
        let animal_position = Arc::clone(&position);
        gate.animal_move(|| {
            *animal_position.lock().unwrap() = 2;
            Ok(())
        })
        .unwrap();

        let wrote = gate
            .write_if_generation_current(expected_generation, || {
                *position.lock().unwrap() = -1;
                Ok(())
            })
            .unwrap();

        assert!(!wrote);
        assert_eq!(*position.lock().unwrap(), 2);
    }

    #[test]
    fn newer_placement_invalidates_an_older_retry() {
        let gate = PositionMoveGate::new();
        let stale_generation = gate.generation();
        let placement_generation = gate
            .place_if_generation_current(stale_generation, || Ok(()))
            .unwrap();
        assert_eq!(placement_generation, Some(stale_generation + 1));
        gate.animal_move(|| Ok(())).unwrap();

        let retried = AtomicBool::new(false);
        let wrote = gate
            .write_if_generation_current(placement_generation.unwrap(), || {
                retried.store(true, Ordering::SeqCst);
                Ok(())
            })
            .unwrap();
        assert!(!wrote);
        assert!(!retried.load(Ordering::SeqCst));
    }

    #[test]
    fn resized_outer_height_keeps_requested_height_and_frame_delta() {
        assert_eq!(resized_outer_height(505, 1.0, 0), 505);
        assert_eq!(resized_outer_height(505, 2.0, 12), 1022);
    }

    #[test]
    fn resize_height_is_bounded_by_work_area_and_reasonable_minimum() {
        assert_eq!(bounded_widget_height(u32::MAX, 1000, 2.0, 12), 494);
        assert_eq!(bounded_widget_height(0, 1000, 2.0, 12), 64);
        assert_eq!(bounded_widget_height(100, 32, 1.0, 0), 32);
        assert_eq!(bounded_widget_height(u32::MAX, 10000, 1.0, 0), 4096);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn pixel_replies_require_current_requests_and_expire_from_send_time() {
        let now = Instant::now();
        let mut state = PointerState::default();
        state.set_areas(Some(PointerInteractiveAreas { revision: 1, ..Default::default() }), 400.0, 500.0);
        let request = PointerSampleRequest { request_id: 1, revision: 1, x: 10.0, y: 20.0 };
        state.pending.push((request, now));
        state.accept_hit(1, 1, 10.0, 20.0, false, now + Duration::from_millis(121));
        assert!(state.hit.is_none());
        state.pending.push((request, now));
        state.accept_hit(1, 2, 10.0, 20.0, false, now);
        assert!(state.hit.is_none());
        state.pending.push((request, now));
        state.accept_hit(1, 1, 13.0, 20.0, false, now);
        assert!(state.hit.is_none());
        state.pending.push((request, now));
        state.accept_hit(1, 1, 10.0, 20.0, false, now + Duration::from_millis(100));
        assert_eq!(state.hit.unwrap().sampled_at, now);
        state.set_areas(Some(PointerInteractiveAreas { revision: 2, ..Default::default() }), 400.0, 500.0);
        state.accept_hit(1, 1, 10.0, 20.0, false, now);
        assert!(state.hit.is_none());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn resize_rejects_early_old_and_wrong_viewport_geometry() {
        let mut state = PointerState::default();
        let areas = |revision, height| Some(PointerInteractiveAreas { revision, viewport_width: Some(400.0), viewport_height: height, ..Default::default() });
        state.set_areas(areas(1, Some(500.0)), 400.0, 500.0);
        state.invalidate(true);
        state.set_areas(areas(2, Some(700.0)), 400.0, 700.0);
        assert!(state.areas.is_none());
        state.invalidate(false);
        state.set_areas(areas(2, Some(700.0)), 400.0, 700.0);
        state.set_areas(areas(3, Some(500.0)), 400.0, 700.0);
        state.set_areas(areas(4, None), 400.0, 700.0);
        assert!(state.areas.is_none());
        state.set_areas(areas(5, Some(700.0)), 400.0, 700.0);
        assert_eq!(state.areas.unwrap().revision, 5);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn pointer_gesture_recovers_and_preserves_drag_suspend_and_double_click() {
        let now = Instant::now();
        let mut gesture = PointerGesture::default();
        assert!(gesture.should_ignore(true, true, false, false, true, now));
        assert!(!gesture.should_ignore(false, true, false, false, true, now));
        assert!(!gesture.should_ignore(true, true, true, false, false, now));
        assert!(!gesture.should_ignore(true, true, false, true, false, now));
        gesture.should_ignore(false, false, false, false, true, now);
        gesture.should_ignore(false, true, false, false, true, now);
        assert!(!gesture.should_ignore(true, false, false, false, true, now));
        assert!(!gesture.should_ignore(true, true, false, false, true, now + Duration::from_millis(200)));
        assert!(gesture.should_ignore(true, false, false, false, false, now + Duration::from_millis(300)));
        assert!(gesture.should_ignore(true, false, false, false, true, now + Duration::from_millis(501)));
    }

    #[cfg(target_os = "macos")]
    fn pointer_areas(role: InteractiveArea) -> PointerInteractiveAreas {
        PointerInteractiveAreas {
            revision: 1,
            enabled: true,
            role: Some(role),
            controls: vec![InteractiveArea { x: 30.0, y: 0.0, width: 100.0, height: 40.0 }],
            ..Default::default()
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn animal_pointer_keeps_a_tight_role_hit_area_and_controls() {
        let areas = pointer_areas(InteractiveArea { x: 20.0, y: 60.0, width: 180.0, height: 200.0 });
        let window = PhysicalPosition::new(2000, 400);
        let now = Instant::now();
        for point in [
            CGPoint { x: 1060.0, y: 330.0 },
            CGPoint { x: 1018.0, y: 335.0 },
            CGPoint { x: 1040.0, y: 210.0 },
        ] {
            assert!(!should_ignore_animal_pointer(
                Some(areas.clone()), Some(point), window, 2.0, None, now
            ));
        }
        assert!(should_ignore_animal_pointer(
            Some(areas.clone()),
            Some(CGPoint { x: 1015.0, y: 335.0 }),
            window,
            2.0,
            None,
            now,
        ));
        assert!(should_ignore_animal_pointer(
            Some(areas),
            Some(CGPoint { x: 1250.0, y: 300.0 }),
            window,
            2.0,
            None,
            now,
        ));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn animal_pointer_uses_only_fresh_matching_alpha_samples_inside_role_bounds() {
        let areas = pointer_areas(InteractiveArea { x: 20.0, y: 60.0, width: 180.0, height: 200.0 });
        let window = PhysicalPosition::new(2000, 400);
        let cursor = Some(CGPoint { x: 1060.0, y: 330.0 });
        let now = Instant::now();
        let hit = |opaque, x, sampled_at| Some(PointerPixelHit {
            request_id: 1,
            revision: 1,
            x,
            y: 130.0,
            opaque,
            sampled_at,
        });

        assert!(!should_ignore_animal_pointer(
            Some(areas.clone()), cursor, window, 2.0, hit(true, 60.0, now), now
        ));
        assert!(should_ignore_animal_pointer(
            Some(areas.clone()), cursor, window, 2.0, hit(false, 60.0, now), now
        ));
        assert!(!should_ignore_animal_pointer(
            Some(areas.clone()),
            cursor,
            window,
            2.0,
            hit(false, 60.0, now - Duration::from_millis(121)),
            now,
        ));
        assert!(!should_ignore_animal_pointer(
            Some(areas), cursor, window, 2.0, hit(false, 70.0, now), now
        ));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn animal_pointer_fails_open_when_unavailable_or_suspended() {
        let areas = pointer_areas(InteractiveArea { x: 20.0, y: 60.0, width: 180.0, height: 200.0 });
        let cursor = Some(CGPoint { x: 0.0, y: 0.0 });
        let window = PhysicalPosition::new(0, 0);
        let now = Instant::now();
        assert!(!should_ignore_animal_pointer(None, cursor, window, 2.0, None, now));
        assert!(!should_ignore_animal_pointer(Some(areas.clone()), None, window, 2.0, None, now));
        assert!(!should_ignore_animal_pointer(
            Some(PointerInteractiveAreas { suspend: true, ..areas }),
            cursor,
            window,
            2.0,
            None,
            now,
        ));
    }

    #[test]
    fn clamps_inside_when_auto_hide_is_disabled() {
        let result = settle_position_in_work_area(
            WidgetPosition { x: 1900, y: 1060 },
            SIZE,
            AREA,
            false,
            1.0,
            VisibleEdges::default(),
            None,
        );
        assert_eq!(result, WidgetPosition { x: 1490, y: 600 });
    }

    #[test]
    fn hides_at_each_edge_but_keeps_visible_pixels() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 20, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: -302, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 1640, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: 1688, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 20 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: 300, y: -304 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 780 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: 300, y: 904 }
        );
    }

    #[test]
    fn leaves_center_positions_unchanged() {
        let position = WidgetPosition { x: 600, y: 400 };
        assert_eq!(
            settle_position_in_work_area(position, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
            position
        );
    }

    #[test]
    fn snaps_only_the_dominant_edge_at_a_corner() {
        let result =
            settle_position_in_work_area(WidgetPosition { x: 20, y: 10 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None);
        assert_eq!(result, WidgetPosition { x: 20, y: -304 });
    }

    #[test]
    fn snaps_when_drag_crosses_an_edge() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 2000, y: 300 }, SIZE, AREA, true, 1.0, VisibleEdges::default(), None),
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
                None,
            ),
            WidgetPosition { x: 3376, y: 1000 }
        );
    }

    #[test]
    fn preserves_saved_offscreen_position_but_keeps_it_reachable() {
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 1688, y: 600 }, SIZE, AREA, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: 1688, y: 600 }
        );
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 5000, y: -5000 }, SIZE, AREA, 1.0, VisibleEdges::default(), None),
            WidgetPosition { x: 1688, y: -304 }
        );
    }

    #[test]
    fn normalizes_scale_to_safe_bounds() {
        assert_eq!(normalize_scale(0.2), 0.75);
        // 上限与 WIDGET_MAX_SCALE（2.0）一致；前端滑杆自身限制在 1.15。
        assert_eq!(normalize_scale(4.0), 2.0);
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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
                visible,
                None,
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

    // ── 内容基准吸附：触发与落点按角色内容矩形计算 ──

    /// 窗口 430×480，角色内容居中偏下：窗口内逻辑矩形 (100, 60, 230, 400)，抓手 64。
    fn content() -> ContentGeometry {
        ContentGeometry {
            rect: InteractiveArea {
                x: 100.0,
                y: 60.0,
                width: 230.0,
                height: 400.0,
            },
            handle: 64,
        }
    }

    #[test]
    fn content_far_from_edge_does_not_snap() {
        // 旧实现按窗口矩形判定：窗口 x=20（距左边缘 20 < 44）就会吸附；
        // 角色实际距左边缘 120px —— 内容基准下不应吸附。
        let result = settle_position_in_work_area(
            WidgetPosition { x: 20, y: 300 },
            SIZE,
            AREA,
            true,
            1.0,
            VisibleEdges::default(),
            Some(content()),
        );
        assert_eq!(result, WidgetPosition { x: 20, y: 300 });
    }

    #[test]
    fn content_based_snap_keeps_handle_visible_at_left_edge() {
        // 角色内容左缘距屏幕左边缘 40px（≤ 触发阈值）→ 吸附，
        // 吸附后内容左缘位于 -64（只露出 64px 抓手）。
        let result = settle_position_in_work_area(
            WidgetPosition { x: -60, y: 300 },
            SIZE,
            AREA,
            true,
            1.0,
            VisibleEdges::default(),
            Some(content()),
        );
        assert_eq!(result, WidgetPosition { x: -164, y: 300 });
        // 验证语义：吸附后内容左缘 = -164 + 100 = -64。
        assert_eq!(result.x + 100, -64);
    }

    #[test]
    fn content_based_snap_works_on_bottom_edge() {
        // 内容下缘 = 780 + 460 = 1240，越过工作区底部（1080）→ 吸附下边缘，
        // 内容下缘落到 1080 + 64 = 1144 → y = 1144 - 460 = 684。
        let result = settle_position_in_work_area(
            WidgetPosition { x: 600, y: 780 },
            SIZE,
            AREA,
            true,
            1.0,
            VisibleEdges::default(),
            Some(content()),
        );
        assert_eq!(result, WidgetPosition { x: 600, y: 684 });
    }

    #[test]
    fn content_clamp_lets_character_touch_the_edge_without_auto_hide() {
        // 关闭自动隐藏时，角色也应该能真正贴到屏幕左缘（窗口允许部分越界）：
        // 用户把内容拖过左缘时，结算把内容左缘收回到 area.x=0 → 窗口 x = -100。
        // （旧实现把整窗夹回屏幕内，角色永远隔着透明边碰不到屏幕边。）
        let result = settle_position_in_work_area(
            WidgetPosition { x: -200, y: 300 },
            SIZE,
            AREA,
            false,
            1.0,
            VisibleEdges::default(),
            Some(content()),
        );
        assert_eq!(result, WidgetPosition { x: -100, y: 300 });
    }

    #[test]
    fn content_preserve_keeps_position_reachable() {
        // 已吸附在左缘的位置必须原样保留（内容仍有 64px 抓手露在屏幕内）。
        assert_eq!(
            preserve_position_in_work_area(
                WidgetPosition { x: -164, y: 300 },
                SIZE,
                AREA,
                1.0,
                VisibleEdges::default(),
                Some(content()),
            ),
            WidgetPosition { x: -164, y: 300 }
        );
        // 远离屏幕的保存位置被拉回到“内容至少露 64px 抓手”的可达范围。
        assert_eq!(
            preserve_position_in_work_area(
                WidgetPosition { x: -9000, y: 300 },
                SIZE,
                AREA,
                1.0,
                VisibleEdges::default(),
                Some(content()),
            ),
            WidgetPosition { x: -164, y: 300 }
        );
    }

    #[test]
    fn content_top_snap_falls_back_to_peek_on_macos() {
        // 内容上缘 = -30 + 60 = 30（≤ 触发阈值）→ 吸附上边缘：y = 0 - 64 - 60 = -124。
        let settled = settle_position_in_work_area(
            WidgetPosition { x: 600, y: -30 },
            SIZE,
            AREA,
            true,
            1.0,
            VisibleEdges::default(),
            Some(content()),
        );
        assert_eq!(settled, WidgetPosition { x: 600, y: -124 });
        // macOS 不允许窗口越过工作区顶部：钳回顶边，交给前端做窗口内上移。
        let (target, peek) = clamp_top_peek(settled, AREA, true);
        assert_eq!(target, WidgetPosition { x: 600, y: 0 });
        assert!(peek, "上边缘被平台钳制时必须让前端做窗口内上移");
    }
}

// ══ Windows 分级鼠标穿透：SetWindowRgn 按角色轮廓裁剪窗口 ══
#[cfg(target_os = "windows")]
mod win32_hit {
    use super::InteractiveArea;
    use std::sync::atomic::{AtomicBool, Ordering};

    /// RECT 用于 Win32 CreateRectRgnIndirect / ExtCreateRegion
    #[repr(C)]
    #[derive(Debug, Clone, Copy)]
    struct RECT {
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    }

    /// RGNDATAHEADER（32 字节），iType=RDH_RECTANGLES(1)
    #[repr(C)]
    struct RgnDataHeader {
        dw_size: u32,          // sizeof(RGNDATAHEADER) = 32
        i_type: u32,           // RDH_RECTANGLES = 1
        n_count: u32,
        n_rgn_size: u32,
        rc_bound: RECT,
    }

    extern "system" {
        fn GetWindowRect(hwnd: isize, rect: *mut RECT) -> i32;
        fn SetWindowRgn(hwnd: isize, hrgn: isize, redraw: i32) -> i32;
        fn CreateRectRgnIndirect(rect: *const RECT) -> isize;
        fn ExtCreateRegion(
            transform: *const std::ffi::c_void,
            n_count: u32,
            data: *const u8,
        ) -> isize;
        fn DeleteObject(obj: isize) -> i32;
        fn GetWindowLongPtrW(hwnd: isize, index: i32) -> isize;
        fn SetWindowLongPtrW(hwnd: isize, index: i32, value: isize) -> isize;
        fn SetLayeredWindowAttributes(
            hwnd: isize,
            color_key: u32,
            alpha: u8,
            flags: u32,
        ) -> i32;
        fn SetWindowPos(
            hwnd: isize,
            insert_after: isize,
            x: i32, y: i32,
            cx: i32, cy: i32,
            flags: u32,
        ) -> i32;
    }

    const GWL_EXSTYLE: i32 = -20;
    const WS_EX_LAYERED: isize = 0x0008_0000;
    const WS_EX_TRANSPARENT: isize = 0x0000_0020;
    const LWA_ALPHA: u32 = 0x02;
    const SWP_NOMOVE: u32 = 0x0002;
    const SWP_NOSIZE: u32 = 0x0001;
    const SWP_NOZORDER: u32 = 0x0004;
    const SWP_NOACTIVATE: u32 = 0x0010;
    const SWP_FRAMECHANGED: u32 = 0x0020;

    static PASSTHROUGH_ON: AtomicBool = AtomicBool::new(false);

    /// 整窗穿透开关：LAYERED + LWA_ALPHA(255) + TRANSPARENT 三件套
    pub unsafe fn set_full_passthrough(hwnd: isize, on: bool) -> bool {
        let mut ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        if on {
            ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT;
        } else {
            ex &= !(WS_EX_LAYERED | WS_EX_TRANSPARENT);
        }
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
        if on {
            SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA);
        }
        SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        ) != 0
    }

    pub fn passthrough_on() -> bool {
        PASSTHROUGH_ON.load(Ordering::SeqCst)
    }

    pub fn toggle_passthrough(hwnd: isize) -> bool {
        let current = PASSTHROUGH_ON.swap(!PASSTHROUGH_ON.load(Ordering::SeqCst), Ordering::SeqCst);
        let on = !current;
        unsafe { set_full_passthrough(hwnd, on) };
        on
    }

    /// 分级穿透：把矩形列表打包成 region 并应用到窗口
    /// region 外不显示也不吃鼠标；传入空 vec 时清除 region（还原矩形窗口）。
    pub unsafe fn apply_hit_rects(
        hwnd: isize,
        rects: &[InteractiveArea],
        scale_factor: f64,
    ) {
        if rects.is_empty() {
            SetWindowRgn(hwnd, 0, 1);
            return;
        }
        let to_physical = |v: f64| (v * scale_factor).round() as i32;
        let mut raw: Vec<RECT> = rects
            .iter()
            .map(|r| {
                let pad = 3i32; // 外扩防啃边
                RECT {
                    left: to_physical(r.x) - pad,
                    top: to_physical(r.y) - pad,
                    right: to_physical(r.x + r.width) + pad,
                    bottom: to_physical(r.y + r.height) + pad,
                }
            })
            .collect();
        if raw.len() == 1 {
            let hrgn = CreateRectRgnIndirect(&raw[0]);
            SetWindowRgn(hwnd, hrgn, 1);
            return;
        }
        // 多个矩形时用 ExtCreateRegion 一次创建
        let hdr_size = std::mem::size_of::<RgnDataHeader>();
        let rect_size = std::mem::size_of::<RECT>();
        let buf_size = hdr_size + raw.len() * rect_size;
        let mut buf = vec![0u8; buf_size];
        let hdr = buf.as_mut_ptr() as *mut RgnDataHeader;
        (*hdr).dw_size = hdr_size as u32;
        (*hdr).i_type = 1; // RDH_RECTANGLES
        (*hdr).n_count = raw.len() as u32;
        (*hdr).n_rgn_size = (raw.len() * rect_size) as u32;
        // 整体外扩包围盒
        let mut bound = RECT { left: i32::MAX, top: i32::MAX, right: i32::MIN, bottom: i32::MIN };
        for r in &raw {
            bound.left = bound.left.min(r.left);
            bound.top = bound.top.min(r.top);
            bound.right = bound.right.max(r.right);
            bound.bottom = bound.bottom.max(r.bottom);
        }
        (*hdr).rc_bound = bound;
        std::ptr::copy_nonoverlapping(
            raw.as_ptr(),
            buf.as_mut_ptr().add(hdr_size) as *mut RECT,
            raw.len(),
        );
        let hrgn = ExtCreateRegion(std::ptr::null(), buf_size as u32, buf.as_ptr());
        if hrgn != 0 {
            SetWindowRgn(hwnd, hrgn, 1);
        }
    }
}

/// 切换挂件整窗穿透模式（看得见但不吃鼠标），供托盘菜单/全局热键调用。
/// 穿透后必须留唤回通道（托盘菜单或 Ctrl+Alt+Q），否则用户再也点不到挂件。
#[tauri::command]
pub fn toggle_widget_passthrough(app: AppHandle) -> Result<bool, String> {
    #[cfg(target_os = "windows")]
    {
        let window = widget_window(&app)?;
        let hwnd = window.hwnd().map_err(|e| format!("获取窗口句柄失败: {e}"))?;
        return Ok(win32_hit::toggle_passthrough(hwnd.0));
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = app;
        Err("穿透模式仅在 Windows 上可用".to_string())
    }
}
