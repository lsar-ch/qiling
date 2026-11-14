export type AnimalGait = "walk" | "run";
/** home = 驻足；standing = 起身准备（静止站起、不转身）；roaming = 移动中；manual = 被拖拽。 */
export type AnimalMobilityPhase = "home" | "standing" | "roaming" | "manual";
export type AnimalFacing = "left" | "front" | "right";

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AnimalMobilityState {
  current: Point;
  home: Point;
  target: Point | null;
  phase: AnimalMobilityPhase;
  movementElapsedMs: number;
  /** 驻足截止时刻（nowMs 时间轴）；到期后继续溜达。 */
  pauseUntilMs: number;
  /** 起身准备截止时刻：这期间窗口静止、朝向保持正面，让 stand_up 完整播完。 */
  standUntilMs: number;
}

export interface AnimalMobilityInput {
  taskActive: boolean;
  dragging: boolean;
  deltaMs: number;
  /** 当前时刻（performance.now 时间轴），用于驻足计时。 */
  nowMs?: number;
  workArea: Rect;
  windowSize: { width: number; height: number };
  random?: () => number;
}

export interface AnimalMobilityFrame {
  state: AnimalMobilityState;
  position: Point;
  gait: AnimalGait | null;
  facing: AnimalFacing;
}

const EDGE_MARGIN = 18;
const WALK_SPEED_PX_PER_SEC = 80;
const RUN_SPEED_PX_PER_SEC = 180;
const ARRIVE_DISTANCE_PX = 2;
// 空闲溜达的驻足时长：到达一个目标后停 4~9 秒再选下一个（用户决策 2026-11-05：
// 空闲时慢走溜达，busy/executing 时才奔跑 —— busy 即 run，取代旧的 walk/run 交替开关）。
const IDLE_PAUSE_MIN_MS = 4000;
const IDLE_PAUSE_SPREAD_MS = 5000;
/**
 * 起身准备时长（用户 2026-11-12 决策）：坐姿 → 站起 → 再转身。
 * stand_up clip = 1.2083s，加上 0.12s crossFade 与一帧调度余量取 1350ms。
 * 这期间 gait=null、facing=front、窗口不位移；期满才发布朝向并开始走动。
 * 否则 facing 会与 stand_up 并行插值（约 0.3s 转完），坐姿尾巴在转身中
 * 从相机遮挡后面露出来、与身体动作脱节。
 */
const STAND_UP_MS = 1350;

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function clampPointForWindow(
  point: Point,
  workArea: Rect,
  windowSize: { width: number; height: number },
): Point {
  const maxX = workArea.x + Math.max(0, workArea.width - windowSize.width);
  const maxY = workArea.y + Math.max(0, workArea.height - windowSize.height);
  return {
    x: Math.round(clamp(point.x, Math.min(workArea.x + EDGE_MARGIN, maxX), maxX)),
    y: Math.round(clamp(point.y, Math.min(workArea.y + EDGE_MARGIN, maxY), maxY)),
  };
}

function chooseTarget(
  workArea: Rect,
  windowSize: { width: number; height: number },
  random: () => number,
): Point {
  const maxX = workArea.x + Math.max(0, workArea.width - windowSize.width);
  const floorY = workArea.y + Math.max(0, workArea.height - windowSize.height);
  return clampPointForWindow(
    {
      x: workArea.x + Math.round(Math.max(0, maxX - workArea.x) * random()),
      y: floorY,
    },
    workArea,
    windowSize,
  );
}

function facingForDelta(dx: number): AnimalFacing {
  if (dx < -12) return "left";
  if (dx > 12) return "right";
  return "front";
}

function idlePauseMs(random: () => number): number {
  return IDLE_PAUSE_MIN_MS + Math.round(IDLE_PAUSE_SPREAD_MS * random());
}

export function createAnimalMobility(position: Point): AnimalMobilityState {
  return {
    current: { ...position },
    home: { ...position },
    target: null,
    phase: "home",
    movementElapsedMs: 0,
    pauseUntilMs: 0,
    standUntilMs: 0,
  };
}

export function setAnimalTemporaryHome(
  state: AnimalMobilityState,
  position: Point,
): AnimalMobilityState {
  return {
    current: { ...position },
    home: { ...position },
    target: null,
    phase: "home",
    movementElapsedMs: 0,
    pauseUntilMs: 0,
    standUntilMs: 0,
  };
}

export function shiftAnimalMobilityForResize(
  state: AnimalMobilityState,
  dy: number,
): AnimalMobilityState {
  const shift = (point: Point): Point => ({ x: point.x, y: point.y + dy });
  return {
    ...state,
    current: shift(state.current),
    home: shift(state.home),
    target: state.target ? shift(state.target) : null,
  };
}

export function updateAnimalMobility(
  previous: AnimalMobilityState,
  input: AnimalMobilityInput,
): AnimalMobilityFrame {
  const state: AnimalMobilityState = {
    ...previous,
    current: { ...previous.current },
    home: { ...previous.home },
    target: previous.target ? { ...previous.target } : null,
  };
  const random = input.random ?? Math.random;
  const now = input.nowMs ?? 0;

  if (input.dragging) {
    state.phase = "manual";
    state.target = null;
  } else if (state.phase === "manual") {
    // 松手：位置由 adoptCurrentPosition 异步重同步，这里不能回置旧 home
    // （旧实现把 current 拉回拖拽前的 home，窗口会瞬移回去），只安排一次驻足。
    state.phase = "home";
    state.target = null;
    state.movementElapsedMs = 0;
    state.pauseUntilMs = now + idlePauseMs(random);
  }

  const startStanding = (): void => {
    // 起身准备：只推进 phase，不挑目标、不移动、不转身。
    state.phase = "standing";
    state.target = null;
    state.movementElapsedMs = 0;
    state.standUntilMs = now + STAND_UP_MS;
  };

  const startRoaming = (): void => {
    state.phase = "roaming";
    state.target = chooseTarget(input.workArea, input.windowSize, random);
    state.movementElapsedMs = 0;
  };

  if (input.taskActive) {
    // busy/executing：连续游走 + 奔跑，不驻足。
    if (state.phase === "home") startRoaming();
  } else if (state.phase === "home") {
    if (state.pauseUntilMs === 0) {
      // 尚未排过驻足（初始/adopt 后）：先驻足一段再出发。
      state.pauseUntilMs = now + idlePauseMs(random);
      return { state, position: { ...state.current }, gait: null, facing: "front" };
    }
    if (state.pauseUntilMs > now) {
      return { state, position: { ...state.current }, gait: null, facing: "front" };
    }
    // 驻足期满：先原地站起（坐姿→站姿），再转身出发。
    startStanding();
    return { state, position: { ...state.current }, gait: null, facing: "front" };
  }

  if (state.phase === "standing") {
    if (now < state.standUntilMs) {
      return { state, position: { ...state.current }, gait: null, facing: "front" };
    }
    startRoaming();
  }

  if (state.phase === "home" || state.phase === "manual" || !state.target) {
    return {
      state,
      position: { ...state.current },
      gait: null,
      facing: "front",
    };
  }

  if (distance(state.current, state.target) <= ARRIVE_DISTANCE_PX) {
    state.current = { ...state.target };
    if (!input.taskActive) {
      // 空闲溜达：到达即驻足，停一会儿再挑下一个目标。
      state.phase = "home";
      state.target = null;
      state.movementElapsedMs = 0;
      state.pauseUntilMs = now + idlePauseMs(random);
      return { state, position: { ...state.current }, gait: null, facing: "front" };
    }
    state.target = chooseTarget(input.workArea, input.windowSize, random);
  }

  const dx = state.target.x - state.current.x;
  const dy = state.target.y - state.current.y;
  const dist = Math.hypot(dx, dy);
  // busy 奔跑，空闲慢走。
  const gait: AnimalGait = input.taskActive ? "run" : "walk";
  const speed = gait === "walk" ? WALK_SPEED_PX_PER_SEC : RUN_SPEED_PX_PER_SEC;
  const step = Math.min(dist, (speed * Math.max(0, input.deltaMs)) / 1000);
  const rawNext = {
    x: state.current.x + (dx / dist) * step,
    y: state.current.y + (dy / dist) * step,
  };
  state.current = clampPointForWindow(rawNext, input.workArea, input.windowSize);
  state.movementElapsedMs += Math.max(0, input.deltaMs);

  return {
    state,
    position: { ...state.current },
    gait,
    facing: facingForDelta(dx),
  };
}
