/**
 * 动物 3D 形象舞台（P0 Spike）：GLB + AnimationMixer + 透明画布。
 * 复用 VrmStage 的渲染配置（alpha + premultipliedAlpha:false）与内容包围盒测量。
 * 不走 VRM：GLTFLoader 直接加载四足 GLB，按抽象动作配置播放。
 */
import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { personaAssetUrl, type AnimalMotionConfig, type PersonaPresentation } from "../api";
import type { ActionTrigger } from "./actions";
import { animalYawForFacing, type AnimalFacing } from "./animalFacing";
import type { AnimalGait, AnimalMobilityPhase } from "./animalMobility";
import { buildAnimalRig, type AnimalRig } from "./animalRig";
import { resolveAnimalClip } from "./animalMotion";
import { bridgeClipFor, bridgeFollowUpFor, departureBridgeFor } from "./animalTransition";
import { samplePointerPixelOpaque, type PointerSampleRequest } from "./animalPixelHit";

/** 循环类 trigger 原地单向循环；其余为一次性动作，播完回 idle。 */
const LOOP_TRIGGERS: ReadonlySet<ActionTrigger> = new Set([
  "idle", "listening", "thinking", "speaking", "executing", "awaiting_approval", "project",
]);

// Restore the 86-frame preview duration after export retimed it to 68 frames.
const IDLE_TAIL_TIME_SCALE = 68 / 86;

export function animalTimeScaleFor(
  clipName: string | null,
  gait: AnimalGait | null = null,
): number {
  if (gait === "run" && clipName === "walk") return 1.35;
  return clipName === "idle_tail" ? IDLE_TAIL_TIME_SCALE : 1;
}

/**
 * 所有循环动作都用 LoopRepeat 原地循环，不再 ping-pong 倒放：
 * walk/run 正放再倒放会变成「往前走一段又倒退」；坐姿等待机等闲置动作本身首尾闭合，
 * 倒放会让角色来回折返，看起来没有固定在原地。只有走路的位移是单向前进的。
 */
export function animalLoopModeFor(name: string, clipName?: string): THREE.AnimationAction["loop"] {
  if (clipName === "walk" || clipName === "run") return THREE.LoopRepeat;
  if (!LOOP_TRIGGERS.has(name as ActionTrigger)) return THREE.LoopOnce;
  return THREE.LoopRepeat;
}

/**
 * 空闲动作轮播：默认让坐姿 / 舔爪 / 趴下 / 睡觉等 clip 在真实挂件里依次出现，
 * 而不是永远只播 idle。可由 persona 的 presentation.animal.idleCycle 覆盖。
 */
const DEFAULT_IDLE_CYCLE = [
  "idle", "sit_idle", "pose_sit_tall", "lick_paw", "crouch",
  "sleep", "stretch", "idle_tail", "knead", "pose_sleep_curl",
];

/** 空闲轮播的默认展示时长（ms）；动作检阅模式另有固定 2400ms。 */
export const IDLE_CYCLE_DWELL_MS = 3800;

/**
 * `sit_idle` 切换前的额外停留余量（ms）。
 * 轮播用墙钟 setTimeout 计时，但动画时间由 mixer.update(delta) 推进，且 delta
 * 被 clamp 到 0.1s；窗口被节流时动画时间会落后于墙钟。再加上切换到下一个 clip
 * 时的 300ms crossFade，若停留时间正好等于 clip 时长，末尾的「抬尾落地 / 弹跳」
 * 会被淡出甚至直接截断。留出余量，保证整段摆动 + 抬尾完整可见。
 */
export const SIT_IDLE_DWELL_MARGIN_MS = 450;

/**
 * 空闲轮播中每个 clip 停留多久。
 *
 * `sit_idle` 必须与整条动作等长：2026-11-12 的 v5 按 v17 原轨迹重建并拉长到
 * 4.8s（左→右落地 → 严格倒放回左 → 放慢的抬尾弹跳）。固定 3800ms 会在抬尾
 * 落地前就切到下一个动作。这里读 GLB 内 clip 的真实 duration 除以 timeScale
 * 得到实播毫秒，再加 SIT_IDLE_DWELL_MARGIN_MS 覆盖 crossFade / 帧率节流；
 * 以后资产再改长度会自动跟随，不用手改常量。其余 clip 维持既定轮播节奏。
 */
export function idleCycleDwellMs(
  clips: readonly THREE.AnimationClip[],
  clipName: string,
): number {
  if (clipName !== "sit_idle") return IDLE_CYCLE_DWELL_MS;
  const clip = clips.find((item) => selectAnimalClips([item])[0] === clipName);
  if (!clip || !Number.isFinite(clip.duration) || clip.duration <= 0) {
    return IDLE_CYCLE_DWELL_MS;
  }
  const scale = animalTimeScaleFor(clipName);
  return Math.max(1, Math.ceil((clip.duration / scale) * 1000)) + SIT_IDLE_DWELL_MARGIN_MS;
}

interface Props {
  personaId: string;
  /** GLB 文件相对 persona 资产目录的路径 */
  glbPath: string;
  trigger: ActionTrigger;
  presentation?: PersonaPresentation | null;
  /** 一次性反馈动作（点击）：播完回落当前状态 trigger */
  oneShot?: { trigger: ActionTrigger; seq: number } | null;
  /** 模型渲染范围（画布 CSS px）回报，供挂件舞台贴合 */
  onContentBox?: (rect: { x: number; y: number; width: number; height: number } | null) => void;
  /** 动物挂件移动方向：左右移动时侧身朝向前进方向，停下回正面。 */
  facing?: AnimalFacing;
  /** 移动状态显式指定 walk/run；为 null 时才播放语义动作。 */
  gait?: AnimalGait | null;
  /**
   * 移动状态机阶段。`standing`（起身准备）时窗口静止、朝向保持正面，
   * 舞台只播 stand_up 并停在站姿末帧；转身和走动等 `roaming` 阶段再开始。
   */
  mobilityPhase?: AnimalMobilityPhase | null;
  /** 动作检阅：按 GLB 内全部 clip 顺序逐个播放（右键菜单开启）。 */
  review?: boolean;
  /** 检阅模式下当前 clip 名回报，用于挂件上显示标签。 */
  onReviewClip?: (name: string | null) => void;
  /** 资产版本：换新 GLB 时改这个值即可让已挂载的挂件重新加载，不必重启客户端。 */
  assetVersion?: string;
}

interface Rig {
  mixer: THREE.AnimationMixer;
  rig: AnimalRig;
  play: (trigger: ActionTrigger, gait?: AnimalGait | null) => void;
  playOneShot: (trigger: ActionTrigger) => void;
  setFacing: (facing: AnimalFacing) => void;
  setReview: (on: boolean) => void;
}

/** 兼容旧资产：导出名可能带前缀；只有一条 Walking 时映射为 walk。 */
export function selectAnimalClips(clips: THREE.AnimationClip[]): string[] {
  if (clips.length === 1 && clips[0].name.toLowerCase().includes("walk")) return ["walk"];
  return clips.map((clip) => (clip.name.split("|").pop() ?? clip.name).toLowerCase());
}

export default function AnimalStage({
  personaId,
  glbPath,
  trigger,
  oneShot,
  presentation,
  onContentBox,
  facing = "front",
  gait = null,
  mobilityPhase = null,
  review = false,
  onReviewClip,
  assetVersion = "v1",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rigRef = useRef<Rig | null>(null);
  const triggerRef = useRef<ActionTrigger>(trigger);
  triggerRef.current = trigger;
  const onContentBoxRef = useRef(onContentBox);
  onContentBoxRef.current = onContentBox;
  const facingRef = useRef<AnimalFacing>(facing);
  facingRef.current = facing;
  const gaitRef = useRef<AnimalGait | null>(gait);
  gaitRef.current = gait;
  const phaseRef = useRef<AnimalMobilityPhase | null>(mobilityPhase);
  phaseRef.current = mobilityPhase;
  const presentationRef = useRef(presentation);
  presentationRef.current = presentation;
  const reviewRef = useRef(review);
  reviewRef.current = review;
  const onReviewClipRef = useRef(onReviewClip);
  onReviewClipRef.current = onReviewClip;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let raf = 0;
    let remeasureTimer = 0;
    let pendingPointerSample: PointerSampleRequest | null = null;
    let sampledPointerRequestId = -1;
    let stopPointerSample: UnlistenFn | null = null;
    /** 异步加载完成后才赋值：清理轮播/检阅计时器。 */
    let disposeCycle: (() => void) | null = null;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      premultipliedAlpha: false,
      antialias: true,
      preserveDrawingBuffer: false,
      powerPreference: "low-power",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    void listen<PointerSampleRequest>("widget-pointer-sample", (event) => {
      pendingPointerSample = event.payload;
    }).then((stop) => {
      if (disposed) stop();
      else stopPointerSample = stop;
    }).catch(() => {
      // Without the native sample stream the widget stays interactive.
    });
    // 自然光的关键：高光做柔和滚降，避免头顶/背脊出现硬邦邦的纯白过曝条
    renderer.toneMapping = THREE.NeutralToneMapping;
    renderer.toneMappingExposure = 1.0;

    const scene = new THREE.Scene();
    scene.visible = false;
    const camera = new THREE.PerspectiveCamera(39.6, 1, 0.1, 100);
    // 自然光布光：天光（环境）打底 + 右前上方暖阳当主光 + 左前弱冷补光 + 左后轮廓光
    // 数值已按 Three.js 物理单位（radiance = albedo * intensity * NdotL / PI）标定，
    // 对应 Blender 预览 render_glb_app.py 的 N5 参数：峰值不超 247/255，无纯白过曝。
    scene.add(new THREE.AmbientLight(0xffffff, 1.35));
    const key = new THREE.DirectionalLight(0xfff6ec, 3.3);
    key.position.set(0.55, 2.4, 1.6);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xe0eaff, 0.7);
    fill.position.set(-0.9, 0.7, 1.2);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0xfffcf7, 0.3);
    rim.position.set(-0.7, 1.4, -1);
    scene.add(rim);

    let measureBox: (() => void) | null = null;
    const fit = (): void => {
      const w = canvas.clientWidth || 338;
      const h = canvas.clientHeight || 338;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      measureBox?.();
    };
    fit();
    const resizeObserver = new ResizeObserver(() => fit());
    resizeObserver.observe(canvas);
    window.addEventListener("resize", fit);

    void (async () => {
      const loader = new GLTFLoader();
      // no-cache 强制 revalidate：GLB 换新后 webview 启发式缓存（无 Cache-Control
      // 头时 WKWebView 按 Last-Modified 估新鲜度）可能长时间供旧文件。
      const resp = await fetch(personaAssetUrl(personaId, glbPath), { cache: "no-cache" });
      if (!resp.ok) throw new Error(`GLB fetch ${resp.status}`);
      const gltf = await loader.parseAsync(await resp.arrayBuffer(), "");
      if (disposed) return;
      const model = gltf.scene;
      model.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) mesh.frustumCulled = false;
      });
      const facingRoot = new THREE.Object3D();
      facingRoot.add(model);
      scene.add(facingRoot);
      let currentYaw = 0;
      let targetYaw = animalYawForFacing(facingRef.current);

      // 取景：bbox 居中，距离按最大维度
      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      // 资产单位可能相差两个数量级；用真实包围盒取景，不能给尺寸设 0.1 下限。
      const maxDim = Math.max(size.x, size.y, size.z, 1e-6);
      const fovRad = (camera.fov * Math.PI) / 180;
      // 相机俯角（2026-11-11 用户在 Blender 视口定的角度）：坐姿 sit_idle
      // 尾根处蒙皮在摆尾时有一团碎面，平视时会露出；抬高约 20° 俯拍恰好
      // 被猫身挡住。参数来自用户视口实测：lens 50mm（fov=2*atan(18/50)≈39.6°）、
      // 俯角 19.64°。fov 变化不影响取景填充（distance 按 tan(fov/2) 反比补偿，
      // 边距 1.85 逻辑不变），仅透视感与 Blender 视口一致。
      const CAM_PITCH_DEG = 19.6;
      const pitchSin = Math.sin((CAM_PITCH_DEG * Math.PI) / 180);
      const pitchCos = Math.cos((CAM_PITCH_DEG * Math.PI) / 180);
      // 边距 1.85：bind 姿势包围盒比动作实际轮廓紧凑（THREE 蒙皮网格的 Box3
      // 只测 bind 姿势）。cat1104_rootfix 逐帧实测（fov30、App 同款取景）：
      // run 正面最坏 NDC 1.143 → 需 1.55×1.143≈1.77；lift/put_down 1.55 时
      // 1.14~1.17 出框。取 1.85 后全部 clip×3 朝向 ≤0.96（2026-11-04 验证）。
      const distance = (maxDim / 2) / Math.tan(fovRad / 2) * 1.85;
      // 侧身旋转的轴心必须落在包围盒中心：模型原点相对中心有 z 向偏移
      // （实测 +0.10，约 0.5×half），绕原点转 90° 会把整只猫横甩出取景框。
      // 轴心对中 + 根位移归零（rootfix）后，侧身半宽回到 z 半宽，1.85 可全覆盖。
      facingRoot.position.set(center.x, 0, center.z);
      // 小尺寸模型的相机距离会小于默认 near plane，必须同步缩小近裁剪面。
      camera.near = Math.min(0.1, distance * 0.1);
      camera.far = Math.max(100, distance * 10);
      camera.updateProjectionMatrix();
      // 相机放在以 bbox 中心为球心、半径 distance、仰角 CAM_PITCH_DEG 的位置：
      // 到目标距离与旧取景一致（bbox 填充不变），仅方向从平视改为俯拍。
      camera.position.set(
        center.x,
        center.y + distance * pitchSin,
        center.z + distance * pitchCos,
      );
      camera.lookAt(center.x, center.y, center.z);

      // 内容包围盒测量（复用 VrmStage 投影逻辑）
      measureBox = (): void => {
        const report = onContentBoxRef.current;
        if (!report) return;
        const w = canvas.clientWidth || 1;
        const h = canvas.clientHeight || 1;
        model.updateMatrixWorld(true);
        const posed = new THREE.Box3().setFromObject(model);
        if (posed.isEmpty()) {
          report(null);
          return;
        }
        const expandX = (posed.max.x - posed.min.x) * 0.08;
        const expandY = (posed.max.y - posed.min.y) * 0.08;
        const expandZ = (posed.max.z - posed.min.z) * 0.08;
        posed.min.x -= expandX; posed.max.x += expandX;
        posed.min.y -= expandY; posed.max.y += expandY;
        posed.min.z -= expandZ; posed.max.z += expandZ;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        const corner = new THREE.Vector3();
        for (let i = 0; i < 8; i++) {
          corner.set(
            i & 1 ? posed.max.x : posed.min.x,
            i & 2 ? posed.max.y : posed.min.y,
            i & 4 ? posed.max.z : posed.min.z,
          );
          corner.project(camera);
          const px = (corner.x * 0.5 + 0.5) * w;
          const py = (1 - (corner.y * 0.5 + 0.5)) * h;
          minX = Math.min(minX, px);
          minY = Math.min(minY, py);
          maxX = Math.max(maxX, px);
          maxY = Math.max(maxY, py);
        }
        report({
          x: Math.max(0, minX),
          y: Math.max(0, minY),
          width: Math.min(w, maxX) - Math.max(0, minX),
          height: Math.min(h, maxY) - Math.max(0, minY),
        });
      };
      measureBox();
      setTimeout(() => {
        if (!disposed) measureBox?.();
      }, 1200);
      // 周期性重测：动物动作持续改变轮廓（呼吸/走路/跳跃），贴边吸附与自动隐藏
      // 几何依赖这份内容矩形，过期就会把角色裁掉一半（与 VrmStage 同款机制）。
      remeasureTimer = window.setInterval(() => {
        if (!disposed && !document.hidden) measureBox?.();
      }, 2000);

      const mixer = new THREE.AnimationMixer(model);
      const clips = gltf.animations;
      const available = selectAnimalClips(clips);
      const rig = buildAnimalRig(model, mixer);
      const resolve = (name: ActionTrigger): string | null =>
        resolveAnimalClip(presentationRef.current?.animal ?? undefined, name, available);

      // 空闲轮播的 clip 列表：优先取 persona 配置，缺省用内置顺序；
      // 只保留 GLB 里真实存在的 clip，避免旧资产只有 5 个动作时报错。
      const animalCfg = presentationRef.current?.animal as unknown as Record<string, unknown> | undefined;
      const rawCycle = animalCfg?.idleCycle;
      const idleCycle: string[] = (Array.isArray(rawCycle) ? rawCycle : DEFAULT_IDLE_CYCLE)
        .map((item) => typeof item === "string" ? item : (item as { clip?: string })?.clip ?? "")
        .map((name) => name.toLowerCase())
        .filter((name) => Boolean(name) && available.includes(name));

      let current: THREE.AnimationAction | null = null;
      // 当前 clip 名：站↔坐桥接要靠它判断「从哪一族来」，不能只看 current.getClip()
      let currentClipName: string | null = null;
      let oneShotPlaying = false;
      let oneShotAction: THREE.AnimationAction | null = null;
      let oneShotUntil = 0;
      const ONE_SHOT_MAX_MS = 15000;
      // 站↔坐过渡：过渡 clip 播完再接目标。
      // bridgeUntil 按 clip 实际时长 + 余量设置：兜底只该比正常 finish 晚一点，
      // 固定 4s 会在 finished 丢失时让角色僵在过渡起点最长 4 秒（僵住+滑行）。
      let bridgeAction: THREE.AnimationAction | null = null;
      let bridgeNext: (() => void) | null = null;
      let bridgeUntil = 0;
      const BRIDGE_MARGIN_MS = 800;

      // 转身闸门（2026-11-12）：stand_up 播放期间保持正面朝向，站起完成后才转身。
      // mobility 的 standing 阶段已在空闲溜达路径做了同样的事；这里再兜住 busy/run
      // 等不经过 standing 的路径，以及转身插值与桥接并行的所有情况。
      let holdFacing = false;
      let pendingYaw: number | null = null;
      const releaseFacing = (): void => {
        holdFacing = false;
        if (pendingYaw !== null) {
          targetYaw = pendingYaw;
          pendingYaw = null;
        }
      };

      const cancelBridge = (): void => {
        bridgeAction = null;
        bridgeNext = null;
        // 桥接被打断时不能让朝向永远锁死。
        releaseFacing();
      };

      const oneShotBusy = (): boolean => {
        if (!oneShotPlaying) return false;
        // 自愈：one-shot 被其他 clip 打断（crossFade 走完 fadeOut 后 mixer 会直接
        // stop 该 action，finished 事件永不触发），此时不能继续锁住 play()。
        if (oneShotAction && current !== oneShotAction) {
          oneShotPlaying = false;
          oneShotAction = null;
          return false;
        }
        if (performance.now() > oneShotUntil) {
          oneShotPlaying = false;
          return false;
        }
        return true;
      };

      const stopCurrentLocomotion = (): void => {
        if (!current) return;
        const clipName = selectAnimalClips([current.getClip()])[0];
        if (clipName !== "walk" && clipName !== "run") return;
        current.fadeOut(0.2);
        current = null;
        currentClipName = null;
      };

      // 站↔坐过渡：先播 sit_down / stand_up（LoopOnce），finish 后接目标 clip。
      // 目标 clip 直接从 start() 起播，不再走 bridgeClipFor 判定，否则会来回桥接
      // （stand_up 自身首帧是坐姿、末帧是站姿）。
      const playBridge = (bridgeName: string, then: () => void): void => {
        const clip = clips.find((item) => selectAnimalClips([item])[0] === bridgeName);
        if (!clip) {
          then();
          return;
        }
        const action = mixer.clipAction(clip);
        action.reset();
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
        action.timeScale = 1;
        action.play();
        if (current && current !== action) current.crossFadeTo(action, 0.12, false);
        current = action;
        currentClipName = bridgeName;
        bridgeAction = action;
        bridgeNext = then;
        // 起身过渡期间锁住转身（保留最后一次朝向请求，过渡结束立即生效）。
        if (bridgeName === "stand_up") holdFacing = true;
        // 兜底时限 = 过渡 clip 实际时长 + 余量；正常情况 finished 事件会先到。
        bridgeUntil = performance.now() + (clip.duration * 1000 + BRIDGE_MARGIN_MS);
      };

      // ── 空闲轮播 / 全动作检阅 ──────────────────────────────────────────
      // 真实挂件默认只有 idle 与 walk 会被触发，坐姿/舔爪/趴下等 clip 从不露面。
      // 这里让 idle 变成一条轮播序列；右键「动作检阅」则按全部 clip 顺序播放。
      let cycleTimer = 0;
      let cycleIndex = 0;
      let cycleMode: "none" | "idle" | "review" = "none";

      const stopCycle = (): void => {
        if (cycleTimer) window.clearTimeout(cycleTimer);
        cycleTimer = 0;
        cycleMode = "none";
      };

      const playClipByName = (clipName: string): void => {
        const clip = clips.find((item) => selectAnimalClips([item])[0] === clipName);
        if (!clip) return;
        const action = mixer.clipAction(clip);
        if (current?.isRunning() && current.getClip() === clip) return;
        cancelBridge();
        action.reset();
        action.setLoop(THREE.LoopRepeat, Infinity);
        action.clampWhenFinished = false;
        action.timeScale = animalTimeScaleFor(clipName);
        action.play();
        if (current && current !== action) current.crossFadeTo(action, 0.3, false);
        current = action;
        currentClipName = clipName;
      };

      const scheduleCycle = (mode: "idle" | "review"): void => {
        const list = mode === "idle" ? idleCycle : available;
        if (list.length === 0) return;
        cycleMode = mode;
        cycleIndex = 0;
        const step = (): void => {
          if (disposed || cycleMode !== mode) return;
          const name = list[cycleIndex % list.length];
          playClipByName(name);
          onReviewClipRef.current?.(mode === "review" ? name : null);
          cycleIndex += 1;
          cycleTimer = window.setTimeout(
            step,
            mode === "review" ? 2400 : idleCycleDwellMs(clips, name),
          );
        };
        step();
      };

      disposeCycle = () => {
        stopCycle();
        onReviewClipRef.current?.(null);
      };

      const play = (name: ActionTrigger, requestedGait: AnimalGait | null = null): void => {
        if (reviewRef.current) return;
        // 移动优先：gait 到来时立即打断 one-shot。窗口已在移动，只允许 walk/run，
        // 否则坐姿/拍爪会叠在滑行上（「没走路也在平移」的变形观感）。
        if (requestedGait && oneShotPlaying) {
          oneShotPlaying = false;
          oneShotAction = null;
        }
        if (oneShotBusy()) return;
        // 起身准备（用户 2026-11-12 要求的顺序：坐姿 → 站起 → 再转身）。
        // mobility 在 standing 阶段让窗口静止、facing=front，这里只播 stand_up
        // 并靠 clampWhenFinished 停在站姿末帧；转身与走动推迟到 roaming 阶段，
        // 避免坐姿尾巴随 facingRoot 在起身途中转到镜头前、与身体动作脱节。
        if (!requestedGait && phaseRef.current === "standing") {
          if (currentClipName === "stand_up" && bridgeAction) return;
          stopCycle();
          cancelBridge();
          playBridge("stand_up", () => {});
          return;
        }
        // idle 轮播期间若被反复 play("idle")（trigger 刷新、one-shot 结束回落等），
        // 不要重置轮播索引 —— 否则 sit_idle 播到一半就被打回 idle，尾巴抬起到
        // 一半就切走（用户 11-12 反馈「整个摆动加尾巴抬起没有播放完」）。
        // 只有真正要走动 / 播放别的 trigger 时才停轮播。
        const keepIdleCycle =
          cycleMode === "idle" && name === "idle" && requestedGait === null;
        cancelBridge();
        if (!keepIdleCycle) stopCycle();
        // 资产已移除 run clip：gait=run 回落 walk（1.35× 提速仍保留）。
        const gaitName = requestedGait === "run" && !available.includes("run") ? "walk" : requestedGait;
        if (name === "idle" && !gaitName && idleCycle.length > 0) {
          if (!keepIdleCycle) scheduleCycle("idle");
          return;
        }
        const clipName = gaitName ?? resolve(name);
        const clip = clipName
          ? clips.find((item) => selectAnimalClips([item])[0] === clipName)
          : undefined;
        if (!clip) {
          stopCurrentLocomotion();
          return;
        }
        if (currentClipName === clipName && current?.isRunning()) return;
        const start = (): void => {
          cancelBridge();
          const action = mixer.clipAction(clip);
          action.reset();
          // 走路是单向前进的动作，循环必须用 LoopRepeat。
          // 用 LoopPingPong 会正放一遍再倒放一遍，看起来就是"往前走一段又开始倒退"。
          const loopMode = animalLoopModeFor(requestedGait ?? name, clipName ?? undefined);
          action.setLoop(loopMode, requestedGait || LOOP_TRIGGERS.has(name) ? Infinity : 1);
          action.timeScale = animalTimeScaleFor(clipName, requestedGait);
          action.clampWhenFinished = true;
          action.play();
          if (current && current !== action) current.crossFadeTo(action, 0.2, false);
          current = action;
          currentClipName = clipName;
        };
        // 起身准备阶段已把 stand_up 独立播完：出发时从站姿末帧经 walk_start 接 walk。
        // 其余情况沿用坐↔站桥接判定。
        const bridge =
          bridgeClipFor(currentClipName, clipName, available)
          ?? (requestedGait ? departureBridgeFor(currentClipName, clipName, available) : null);
        if (bridge) {
          const followUp = bridgeFollowUpFor(bridge, clipName ?? "", available);
          playBridge(bridge, () => {
            if (followUp) playBridge(followUp, start);
            else start();
          });
          return;
        }
        start();
      };

      const playOneShot = (name: ActionTrigger): void => {
        if (oneShotBusy() || reviewRef.current) return;
        // 走动中（gait=walk/run）不做一次性动作：窗口在移动时只允许 walk/run 播放，
        // 否则坐姿/拍爪会叠在滑行上，看起来像「没走路也在平移」的变形。
        // 起身准备阶段同样不接 one-shot，避免打断 stand_up 停在半站半坐。
        if (gaitRef.current || phaseRef.current === "standing") return;
        cancelBridge();
        stopCycle();
        const clipName = resolve(name);
        const clip = clipName
          ? clips.find((item) => selectAnimalClips([item])[0] === clipName)
          : undefined;
        if (!clip) {
          stopCurrentLocomotion();
          return;
        }
        const start = (): void => {
          cancelBridge();
          oneShotPlaying = true;
          oneShotAction = mixer.clipAction(clip);
          oneShotUntil = performance.now() + ONE_SHOT_MAX_MS;
          const action = oneShotAction;
          action.reset();
          action.setLoop(THREE.LoopOnce, 1);
          action.clampWhenFinished = true;
          action.timeScale = animalTimeScaleFor(clipName);
          action.play();
          if (current && current !== action) current.crossFadeTo(action, 0.2, false);
          current = action;
          currentClipName = clipName;
        };
        const bridge = bridgeClipFor(currentClipName, clipName, available);
        if (bridge) {
          playBridge(bridge, start);
          return;
        }
        start();
      };

      const setFacing = (next: AnimalFacing): void => {
        const yaw = animalYawForFacing(next);
        if (holdFacing) {
          pendingYaw = yaw;
          return;
        }
        targetYaw = yaw;
      };

      const setReview = (on: boolean): void => {
        reviewRef.current = on;
        if (on) {
          if (cycleMode === "review") return;
          stopCycle();
          oneShotPlaying = false;
          oneShotAction = null;
          scheduleCycle("review");
        } else {
          if (cycleMode !== "review") return;
          stopCycle();
          onReviewClipRef.current?.(null);
          play(triggerRef.current, gaitRef.current);
        }
      };

      rigRef.current = { mixer, rig, play, playOneShot, setFacing, setReview };

      mixer.addEventListener("finished", ({ action }) => {
        if (action === bridgeAction) {
          bridgeAction = null;
          const next = bridgeNext;
          bridgeNext = null;
          // 站起过渡结束：此时才允许应用（此前缓存的）转身请求。
          releaseFacing();
          next?.();
          return;
        }
        if (action !== oneShotAction) return;
        oneShotPlaying = false;
        oneShotAction = null;
        play(
          LOOP_TRIGGERS.has(triggerRef.current) ? triggerRef.current : "idle",
          gaitRef.current,
        );
      });

      if (reviewRef.current) scheduleCycle("review");
      else play(triggerRef.current, gaitRef.current);
      if (disposed) return;
      mixer.update(0);
      scene.visible = true;

      const clock = new THREE.Clock();
      const tick = (): void => {
        if (disposed) return;
        raf = requestAnimationFrame(tick);
        const delta = Math.min(clock.getDelta(), 0.1);
        const blend = 1 - Math.exp(-10 * delta);
        currentYaw += (targetYaw - currentYaw) * blend;
        if (Math.abs(targetYaw - currentYaw) > 0.0001) {
          facingRoot.rotation.y = currentYaw;
        }
        // 过渡 clip 的 finished 事件偶发不触发（mixer 被 reset / 切后台），加一道超时兜底，
        // 否则会卡在 sit_down / stand_up 的末帧上。
        if (bridgeAction && performance.now() > bridgeUntil) {
          bridgeAction = null;
          const next = bridgeNext;
          bridgeNext = null;
          releaseFacing();
          next?.();
        }
        mixer.update(delta);
        renderer.render(scene, camera);
        const pointerSample = pendingPointerSample;
        if (pointerSample && pointerSample.requestId !== sampledPointerRequestId) {
          sampledPointerRequestId = pointerSample.requestId;
          const opaque = samplePointerPixelOpaque(
            renderer.getContext(),
            canvas.getBoundingClientRect(),
            pointerSample.x,
            pointerSample.y,
          );
          void invoke("set_widget_animal_pixel_hit", { ...pointerSample, opaque }).catch(() => {
            // Readback acknowledgement is best-effort; Rust fails closed without it.
          });
        }
      };
      raf = requestAnimationFrame(tick);
    })().catch((err) => {
      console.warn("[AnimalStage] GLB 加载失败，保持 2D 占位", err);
    });

    return () => {
      disposed = true;
      stopPointerSample?.();
      disposeCycle?.();
      cancelAnimationFrame(raf);
      window.clearInterval(remeasureTimer);
      resizeObserver.disconnect();
      window.removeEventListener("resize", fit);
      onContentBoxRef.current?.(null);
      const rig = rigRef.current;
      rigRef.current = null;
      if (rig) rig.mixer.stopAllAction();
      renderer.dispose();
    };
  }, [personaId, glbPath, assetVersion]);

  // phase 也在依赖里：home→standing 时 gait/trigger 可能都不变，
  // 但仍需要一次 play() 来起播 stand_up；standing→roaming 则接 walk_start→walk。
  useEffect(() => {
    rigRef.current?.play(trigger, gait);
  }, [gait, trigger, mobilityPhase]);

  useEffect(() => {
    rigRef.current?.setReview(review);
  }, [review]);

  useEffect(() => {
    rigRef.current?.setFacing(facing);
  }, [facing]);

  useEffect(() => {
    if (!oneShot) return;
    rigRef.current?.playOneShot(oneShot.trigger);
  }, [oneShot?.trigger, oneShot?.seq]);

  return <canvas ref={canvasRef} className="vrm-canvas" aria-hidden="true" />;
}
