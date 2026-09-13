use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize};

const WIDGET_LABEL: &str = "widget";
const WIDGET_EDGE_MARGIN: i32 = 18;
const WIDGET_EDGE_TRIGGER: i32 = 44;
// The default artwork has a large transparent area on its left, so the right-edge
// snap needs to retain more pixels to keep the character itself visible.
const WIDGET_VISIBLE_LEFT_EDGE: i32 = 128;
const WIDGET_VISIBLE_RIGHT_EDGE: i32 = 232;
const WIDGET_VISIBLE_TOP_EDGE: i32 = 176;
const WIDGET_VISIBLE_BOTTOM_EDGE: i32 = 176;
// ponytail: portable Tauri has no drag-release event, so quiet time approximates the end.
// Replace it with a platform drag-end event if pausing during a drag feels premature.
const WIDGET_DRAG_SETTLE_DELAY: Duration = Duration::from_millis(350);
const WIDGET_MIN_SCALE: f64 = 0.75;
const WIDGET_MAX_SCALE: f64 = 1.15;
const WIDGET_PREFERENCES_FILE: &str = "widget.json";

#[cfg(target_os = "macos")]
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn CGEventSourceButtonState(state_id: i32, button: u32) -> bool;
}

#[cfg(target_os = "macos")]
fn primary_mouse_down() -> bool {
    // Combined session state, left mouse button. No input monitoring permission is required.
    unsafe { CGEventSourceButtonState(0, 0) }
}

#[cfg(not(target_os = "macos"))]
fn primary_mouse_down() -> bool {
    false
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
}

impl Default for WidgetPreferences {
    fn default() -> Self {
        Self {
            x: None,
            y: None,
            monitor: None,
            auto_hide: true,
            scale: 1.0,
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
}

impl WidgetRuntimeState {
    pub fn new(app: AppHandle) -> Self {
        let (move_tx, move_rx) = mpsc::channel();
        let dragging = Arc::new(AtomicBool::new(false));
        let worker_dragging = Arc::clone(&dragging);
        thread::spawn(move || settle_worker(app, move_rx, worker_dragging));
        Self { move_tx, dragging }
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

    let visible_left = ((WIDGET_VISIBLE_LEFT_EDGE as f64 * scale_factor).round() as i64).min(width);
    let visible_right =
        ((WIDGET_VISIBLE_RIGHT_EDGE as f64 * scale_factor).round() as i64).min(width);
    let visible_top = ((WIDGET_VISIBLE_TOP_EDGE as f64 * scale_factor).round() as i64).min(height);
    let visible_bottom =
        ((WIDGET_VISIBLE_BOTTOM_EDGE as f64 * scale_factor).round() as i64).min(height);
    let mut x = clamped_x;
    let mut y = clamped_y;
    match edge {
        0 => x = area.x as i64 - width + visible_left,
        1 => x = area.right() - visible_right,
        2 => y = area.y as i64 - height + visible_bottom,
        3 => y = area.bottom() - visible_top,
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
) -> WidgetPosition {
    let width = size.width as i64;
    let height = size.height as i64;
    let visible_left = ((WIDGET_VISIBLE_LEFT_EDGE as f64 * scale_factor).round() as i64).min(width);
    let visible_right =
        ((WIDGET_VISIBLE_RIGHT_EDGE as f64 * scale_factor).round() as i64).min(width);
    let visible_top = ((WIDGET_VISIBLE_TOP_EDGE as f64 * scale_factor).round() as i64).min(height);
    let visible_bottom =
        ((WIDGET_VISIBLE_BOTTOM_EDGE as f64 * scale_factor).round() as i64).min(height);
    let min_x = area.x as i64 - width + visible_left;
    let max_x = area.right() - visible_right;
    let min_y = area.y as i64 - height + visible_bottom;
    let max_y = area.bottom() - visible_top;
    WidgetPosition {
        x: (position.x as i64).clamp(min_x.min(max_x), max_x) as i32,
        y: (position.y as i64).clamp(min_y.min(max_y), max_y) as i32,
    }
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
    let settled = match mode {
        PositionMode::Preserve => {
            preserve_position_in_work_area(position, size, area, scale_factor)
        }
        PositionMode::ClampInside => {
            settle_position_in_work_area(position, size, area, false, scale_factor)
        }
        PositionMode::SnapToEdge => {
            settle_position_in_work_area(position, size, area, true, scale_factor)
        }
    };
    window
        .set_position(PhysicalPosition::new(settled.x, settled.y))
        .map_err(|error| format!("移动挂件失败: {error}"))?;
    preferences.x = Some(settled.x);
    preferences.y = Some(settled.y);
    preferences.monitor = monitor_name;
    Ok(())
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
        );
        assert_eq!(result, WidgetPosition { x: 1490, y: 600 });
    }

    #[test]
    fn hides_at_each_edge_but_keeps_visible_pixels() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 20, y: 300 }, SIZE, AREA, true, 1.0),
            WidgetPosition { x: -302, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 1640, y: 300 }, SIZE, AREA, true, 1.0),
            WidgetPosition { x: 1688, y: 300 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 20 }, SIZE, AREA, true, 1.0),
            WidgetPosition { x: 300, y: -304 }
        );
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 300, y: 780 }, SIZE, AREA, true, 1.0),
            WidgetPosition { x: 300, y: 904 }
        );
    }

    #[test]
    fn leaves_center_positions_unchanged() {
        let position = WidgetPosition { x: 600, y: 400 };
        assert_eq!(
            settle_position_in_work_area(position, SIZE, AREA, true, 1.0),
            position
        );
    }

    #[test]
    fn snaps_only_the_dominant_edge_at_a_corner() {
        let result =
            settle_position_in_work_area(WidgetPosition { x: 20, y: 10 }, SIZE, AREA, true, 1.0);
        assert_eq!(result, WidgetPosition { x: 20, y: -304 });
    }

    #[test]
    fn snaps_when_drag_crosses_an_edge() {
        assert_eq!(
            settle_position_in_work_area(WidgetPosition { x: 2000, y: 300 }, SIZE, AREA, true, 1.0),
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
            ),
            WidgetPosition { x: 3376, y: 1000 }
        );
    }

    #[test]
    fn preserves_saved_offscreen_position_but_keeps_it_reachable() {
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 1688, y: 600 }, SIZE, AREA, 1.0),
            WidgetPosition { x: 1688, y: 600 }
        );
        assert_eq!(
            preserve_position_in_work_area(WidgetPosition { x: 5000, y: -5000 }, SIZE, AREA, 1.0),
            WidgetPosition { x: 1688, y: -304 }
        );
    }

    #[test]
    fn normalizes_scale_to_safe_bounds() {
        assert_eq!(normalize_scale(0.2), 0.75);
        assert_eq!(normalize_scale(4.0), 1.15);
        assert_eq!(normalize_scale(f64::NAN), 1.0);
    }
}
