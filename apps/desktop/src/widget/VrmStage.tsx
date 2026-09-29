/**
 * VRM 3D 形象舞台：three-vrm 渲染 + VRMA 动作 + 表情/眨眼 + tier-1 口型同步。
 *
 * 渲染配置由 /tmp/vrm-tauri-spike 实测锁定（WKWebView 透明合成 + 58fps），勿随意改：
 * alpha + premultipliedAlpha:false（Windows DComp 黑底修法）、无 preserveDrawingBuffer。
 * 详见 docs/WIDGET-VRM-3D-PLAN.md。
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { motionLibraryUrl, personaAssetUrl, type ExpressionEmotion, type VrmMotionConfig } from "../api";
import type { ActionTrigger } from "./actions";
import { pickVrmClip } from "./vrmClips";
import { lipSyncBus } from "./lipSync";
import { onFollowUpdate, offFollowUpdate } from "./mouseFollow";

/** 循环类 trigger 用 ping-pong 循环；其余为一次性动作，播完回 idle。 */
const LOOP_TRIGGERS: ReadonlySet<ActionTrigger> = new Set([
  "idle", "listening", "thinking", "speaking", "executing", "awaiting_approval",
]);

const EMOTION_EXPRESSION: Record<ExpressionEmotion, string> = {
  success: "happy",
  error: "angry",
  thinking: "neutral",
  confused: "neutral",
  attentive: "relaxed",
  neutral: "neutral",
  happy: "happy",
  sad: "sad",
  surprised: "surprised",
};

const CROSSFADE_S = 0.2;      // 硬切会闪 bind pose，必须交叉淡化
const BLINK_MS = 140;         // 单次眨眼时长
const LIP_GATE = 0.06;        // 归一化 RMS 静音门限（spike 实测值）
const LIP_SCALE = 1.6;        // RMS→aa 增益（spike 实测值）
const LIP_PEAK_DECAY = 0.9995; // autogain 峰值衰减；缺 autogain 时 aa 峰值仅 0.35，嘴不动

interface Props {
  personaId: string;
  /** VRM 文件相对 persona 资产目录的路径 */
  vrmPath: string;
  trigger: ActionTrigger;
  emotion: ExpressionEmotion;
  /** 动作实验室调参：循环 trigger + 交叉淡化时长 */
  vrmConfig?: VrmMotionConfig | null;
  /** 空闲重挑间隔（presentation.animations.idle_action_interval_ms），<=0 关闭 */
  idleIntervalMs?: number;
  /**
   * 一次性反馈动作（点击/悬停）：播完回落到当前状态 trigger，不改变状态。
   * 靠计数器 seq 驱动重复触发；仅由 Widget 在非播报的空闲态推入。
   */
  oneShot?: { trigger: ActionTrigger; seq: number } | null;
}

interface Rig {
  vrm: VRM;
  mixer: THREE.AnimationMixer;
  play: (trigger: ActionTrigger) => Promise<void>;
  /** 播放一次性反馈动作，结束后回落当前状态动作 */
  playOneShot: (trigger: ActionTrigger) => Promise<void>;
}

export default function VrmStage({
  personaId,
  vrmPath,
  trigger,
  emotion,
  vrmConfig,
  idleIntervalMs,
  oneShot,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rigRef = useRef<Rig | null>(null);
  const triggerRef = useRef<ActionTrigger>(trigger);
  const vrmConfigRef = useRef(vrmConfig);
  vrmConfigRef.current = vrmConfig;
  const emotionRef = useRef<ExpressionEmotion>(emotion);
  triggerRef.current = trigger;
  emotionRef.current = emotion;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let raf = 0;
    let followCbRef: ((dx: number, dy: number) => void) | null = null;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      premultipliedAlpha: false,
      antialias: true,
      preserveDrawingBuffer: false,
      powerPreference: "low-power",
    });
    // Retina 下 pixelRatio=1 会把低分辨率画布放大，导致模型和透明边缘发糊。
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    scene.visible = false; // 首帧 shader 编译卡 0.5-1.9s，加载完成前不显示
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(0, 2.2, 1.2);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-0.8, 1.6, -1);
    scene.add(fill);

    const fit = (): void => {
      const w = canvas.clientWidth || 338;
      const h = canvas.clientHeight || 338;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    fit();
    window.addEventListener("resize", fit);

    void (async () => {
      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));
      const resp = await fetch(personaAssetUrl(personaId, vrmPath));
      if (!resp.ok) throw new Error(`VRM fetch ${resp.status}`);
      const gltf = await loader.parseAsync(await resp.arrayBuffer(), "");
      if (disposed) return;
      const vrm = gltf.userData.vrm as VRM;
      VRMUtils.rotateVRM0(vrm);
      VRMUtils.removeUnnecessaryVertices(vrm.scene);
      // 不要调用 VRMUtils.combineSkeletons()：它会重组 skinIndex，把礼帽等
      // 挂在头部 spring 骨上的顶点绑错骨，运行时整顶帽子不渲染。
      vrm.scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) mesh.frustumCulled = false;
      });
      scene.add(vrm.scene);

      // 取景：humanoid 头/脚骨骼算身高，兜底 bbox（spike 验证过的参数）
      const box = new THREE.Box3().setFromObject(vrm.scene);
      const headNode = vrm.humanoid?.getNormalizedBoneNode("head");
      const footNode =
        vrm.humanoid?.getNormalizedBoneNode("leftFoot") ??
        vrm.humanoid?.getNormalizedBoneNode("rightFoot");
      const headY = headNode ? headNode.getWorldPosition(new THREE.Vector3()).y : box.max.y;
      const feetY = footNode ? footNode.getWorldPosition(new THREE.Vector3()).y : box.min.y;
      const height = Math.max(0.1, headY - feetY);
      const targetY = headY - height * 0.4;
      const fovRad = (camera.fov * Math.PI) / 180;
      const distance = Math.max(((height / 2) / Math.tan(fovRad / 2)) * 1.6, 0.6);
      camera.position.set(0, targetY + height * 0.4, distance);
      camera.lookAt(0, targetY, 0);

      const mixer = new THREE.AnimationMixer(vrm.scene);
      const vrmaLoader = new GLTFLoader();
      vrmaLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));
      // clip 按**文件名**缓存：同一 trigger 可有多条候选，按 trigger 建键会串味。
      const clips = new Map<string, THREE.AnimationClip | null>();
      const clipPlayedAt: Record<string, number> = {};
      let current: THREE.AnimationAction | null = null;
      let currentClipName: string | null = null;
      // 一次性反馈动作在播期间不抢戏：状态切换与空闲重挑都要等它收尾
      let oneShotPlaying = false;

      const fetchClipBytes = async (clipName: string): Promise<ArrayBuffer | null> => {
        // 共享动作库优先（male / female），库里没有才回退角色自己的 vrma/。
        const library = vrmConfigRef.current?.library;
        if (library) {
          const shared = await fetch(motionLibraryUrl(library, `${clipName}.vrma`));
          if (shared.ok) return shared.arrayBuffer();
        }
        const local = await fetch(personaAssetUrl(personaId, `vrma/${clipName}.vrma`));
        return local.ok ? local.arrayBuffer() : null;
      };

      const ensureClip = async (clipName: string): Promise<THREE.AnimationClip | null> => {
        if (clips.has(clipName)) return clips.get(clipName) ?? null;
        clips.set(clipName, null); // 占位防重复加载；404 即视为缺失
        try {
          const bytes = await fetchClipBytes(clipName);
          if (!bytes) return null;
          const g = await vrmaLoader.parseAsync(bytes, "");
          const anims = g.userData.vrmAnimations as
            | Parameters<typeof createVRMAnimationClip>[0][]
            | undefined;
          if (!anims?.length) return null;
          const clip = createVRMAnimationClip(anims[0], vrm);
          clips.set(clipName, clip);
          return clip;
        } catch {
          return null;
        }
      };

      const play = async (name: ActionTrigger): Promise<void> => {
        if (oneShotPlaying) return;
        // 多候选：按 weight 随机挑，cooldownMs 挡刚播过的；全在冷却就保持当前动作。
        const choice = pickVrmClip(
          name,
          vrmConfigRef.current?.actions?.[name],
          clipPlayedAt,
          Date.now(),
        );
        if (!choice) return;
        // 抽回正在播的同一条：直接放行，重播会让循环动作跳一下
        if (choice.clip === currentClipName && current?.isRunning()) return;
        const clip = await ensureClip(choice.clip);
        if (disposed || !clip) {
          // 片段被删/改名：用冷却机制永久排除，否则每次重挑都撞它，后面的候选永远轮不到
          clipPlayedAt[choice.clip] = Number.POSITIVE_INFINITY;
          return;
        }
        clipPlayedAt[choice.clip] = Date.now();
        currentClipName = choice.clip;
        const action = mixer.clipAction(clip, vrm.scene);
        action.reset();
        const cfg = vrmConfigRef.current;
        const loopTriggers = cfg?.loop_triggers?.length
          ? new Set(cfg.loop_triggers)
          : LOOP_TRIGGERS;
        // crossFadeTo 收的是秒，配置是毫秒（旧代码漏除 1000，200ms 被当成 200s）
        const crossfade = cfg?.crossfade_ms ? cfg.crossfade_ms / 1000 : CROSSFADE_S;
        // 状态动作永远走循环（一次性反馈由 playOneShot 负责），
        // 且每次重播前重新 setLoop，避免上一条一次性动作把 loop 残留成本条的状态。
        action.setLoop(
          loopTriggers.has(name) ? THREE.LoopPingPong : THREE.LoopOnce,
          loopTriggers.has(name) ? Infinity : 1,
        );
        action.play();
        if (current && current !== action) current.crossFadeTo(action, crossfade, false);
        current = action;
      };

      const playOneShot = async (name: ActionTrigger): Promise<void> => {
        // 反馈动作也走多候选；候选全在冷却时本次不播（与 2D 动作表行为一致）。
        const choice = pickVrmClip(
          name,
          vrmConfigRef.current?.actions?.[name],
          clipPlayedAt,
          Date.now(),
        );
        if (!choice) return;
        const clip = await ensureClip(choice.clip);
        if (disposed || !clip) {
          clipPlayedAt[choice.clip] = Number.POSITIVE_INFINITY;
          return;
        }
        clipPlayedAt[choice.clip] = Date.now();
        currentClipName = choice.clip;
        oneShotPlaying = true;
        const action = mixer.clipAction(clip, vrm.scene);
        action.reset();
        action.setEffectiveTimeScale(choice.timeScale);
        const cfg = vrmConfigRef.current;
        const crossfade = cfg?.crossfade_ms ? cfg.crossfade_ms / 1000 : CROSSFADE_S;
        // 重播 N 次后再回落；LoopRepeat 到次数会触发 finished（LoopOnce 也触发）
        action.setLoop(THREE.LoopRepeat, choice.repeat);
        action.clampWhenFinished = true;
        action.play();
        if (current && current !== action) current.crossFadeTo(action, crossfade, false);
        current = action;
      };

      // 一次性动作（反馈/状态单次）播完 → 回落**当前**状态 trigger，而不是硬编码 idle，
      // 否则思考中点击会把角色降级到待机。循环动作不触发 finished，天然不会误入。
      mixer.addEventListener("finished", () => {
        oneShotPlaying = false;
        void play(triggerRef.current);
      });

      rigRef.current = { vrm, mixer, play, playOneShot };

      // Phase 1: VRM lookAt — 眼球/头部跟随鼠标
      // target 必须加到 scene（世界坐标），不能加到 vrm.scene（本地坐标），
      // 否则 position 与 headPos 坐标系不一致，lookAt 无效。
      const lookAtTarget = new THREE.Object3D();
      scene.add(lookAtTarget);
      // 初始位置：角色正前方远处，让眼球居中
      lookAtTarget.position.set(0, targetY, distance + 1);
      if (vrm.lookAt) {
        vrm.lookAt.target = lookAtTarget;
        // 诊断：检查 lookAt 骨骼映射
        const la = vrm.lookAt as any;
        console.log("[VrmStage] lookAt enabled", {
          hasApplier: !!la._applier,
          applierType: la._applier?.constructor?.name,
          leftEye: !!vrm.humanoid?.getNormalizedBoneNode("leftEye"),
          rightEye: !!vrm.humanoid?.getNormalizedBoneNode("rightEye"),
          head: !!vrm.humanoid?.getNormalizedBoneNode("head"),
        });
      } else {
        console.warn("[VrmStage] vrm.lookAt is null/undefined — this VRM model has no lookAt config");
      }
      const lookAtBase = new THREE.Vector3(0, targetY, distance + 1);
      followCbRef = (dx: number, dy: number): void => {
        // 在角色前方虚拟平面上移动 target
        // dx/dy ∈ [-1,1]，映射到 ±2m 水平 / ±1.5m 垂直（大范围内确保可见）
        lookAtTarget.position.set(
          lookAtBase.x + dx * 2,
          lookAtBase.y - dy * 1.5,
          lookAtBase.z,
        );
      };
      onFollowUpdate(followCbRef);

      // 启动测试：强制大偏转 1.5 秒后回中，验证 lookAt 是否生效
      followCbRef(1, 0.5);
      setTimeout(() => followCbRef?.(0, 0), 1500);

      await play(triggerRef.current);
      if (disposed) return;
      // 显示前先推一帧，避免闪 bind pose
      vrm.update(0);
      mixer.update(0);
      scene.visible = true;

      // 渲染循环：眨眼 + 口型 + 情绪表情平滑
      const clock = new THREE.Clock();
      let td: Uint8Array<ArrayBuffer> | null = null;
      let peakRms = 0;
      let aa = 0;
      let blinkStart = -1;
      let nextBlink = performance.now() + 2000 + Math.random() * 4000;
      const emoWeights = new Map<string, number>();

      const tick = (): void => {
        if (disposed) return;
        raf = requestAnimationFrame(tick);
        const delta = Math.min(clock.getDelta(), 0.1);
        const now = performance.now();
        const em = vrm.expressionManager;

        if (em) {
          // 眨眼：随机间隔 + 正弦脉冲
          if (blinkStart < 0 && now >= nextBlink) blinkStart = now;
          let blink = 0;
          if (blinkStart >= 0) {
            const t = now - blinkStart;
            if (t >= BLINK_MS) {
              blinkStart = -1;
              nextBlink = now + 2000 + Math.random() * 4000;
            } else {
              blink = Math.sin((Math.PI * t) / BLINK_MS);
            }
          }
          em.setValue("blink", blink);

          // 口型 tier-1：AnalyserNode RMS + autogain → aa（算法为 spike 实测通过的参数）
          const analyser = lipSyncBus.analyser;
          let lipTarget = 0;
          if (analyser) {
            if (!td || td.length !== analyser.frequencyBinCount) {
              td = new Uint8Array(analyser.frequencyBinCount);
            }
            analyser.getByteTimeDomainData(td);
            let sum = 0;
            for (let i = 0; i < td.length; i++) {
              const v = (td[i] - 128) / 128;
              sum += v * v;
            }
            const rms = Math.sqrt(sum / td.length);
            if (rms > peakRms) peakRms = rms;
            peakRms *= LIP_PEAK_DECAY;
            const norm = peakRms > 1e-4 ? rms / peakRms : 0;
            lipTarget = Math.min(1, Math.max(0, (norm - LIP_GATE) * LIP_SCALE));
          } else {
            peakRms *= 0.95;
          }
          aa += (lipTarget - aa) * (lipTarget > aa ? 0.55 : 0.18); // 快攻慢放
          if (aa < 0.005) aa = 0;
          em.setValue("aa", aa);

          // 情绪表情：向目标权重指数平滑
          const want = EMOTION_EXPRESSION[emotionRef.current] ?? "neutral";
          if (!emoWeights.has(want)) emoWeights.set(want, 0);
          for (const [name, w] of emoWeights) {
            const target = name === want ? 1 : 0;
            const next = w + (target - w) * Math.min(1, delta * 6);
            if (next < 0.01 && target === 0) {
              em.setValue(name, 0);
              emoWeights.delete(name);
            } else {
              emoWeights.set(name, next);
              em.setValue(name, next);
            }
          }
        }

        vrm.update(delta);
        mixer.update(delta);
        renderer.render(scene, camera);
      };
      raf = requestAnimationFrame(tick);
    })().catch((err) => {
      console.warn("[VrmStage] VRM 加载失败，保持 2D 占位", err);
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", fit);
      const rig = rigRef.current;
      rigRef.current = null;
      if (followCbRef) offFollowUpdate(followCbRef);
      // 卸载时释放 GPU 资源：停 mixer 再释放 geometry/skeleton/material/texture，
      // 否则切换 persona 时旧模型的显存会持续泄漏。
      if (rig) {
        rig.mixer.stopAllAction();
        VRMUtils.deepDispose(rig.vrm.scene);
      }
      renderer.dispose();
    };
  }, [personaId, vrmPath]);

  // trigger 变化 → 切换动作（加载完成前的 trigger 由 setup 内的首播兜底）
  useEffect(() => {
    void rigRef.current?.play(trigger);
  }, [trigger]);

  // 一次性反馈动作：seq 变化即重播（同一点击连点也能再次触发）
  useEffect(() => {
    if (!oneShot) return;
    void rigRef.current?.playOneShot(oneShot.trigger);
  }, [oneShot?.trigger, oneShot?.seq]);

  // 常驻状态重挑：循环类 trigger（listening / idle / …）按 idle_action_interval_ms
  // 重新抽候选（带抖动）。不重挑就只有第一条从头循环到尾，多候选永远轮不到。
  useEffect(() => {
    const loops = vrmConfig?.loop_triggers?.length
      ? new Set<string>(vrmConfig.loop_triggers)
      : LOOP_TRIGGERS;
    if (!loops.has(trigger) || !idleIntervalMs || idleIntervalMs <= 0) return;
    let disposed = false;
    let timer: number | undefined;
    const schedule = (): void => {
      timer = window.setTimeout(() => {
        if (disposed) return;
        if (!document.hidden) void rigRef.current?.play(trigger);
        schedule();
      }, idleIntervalMs * (0.8 + Math.random() * 0.4));
    };
    schedule();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [trigger, idleIntervalMs, vrmConfig]);

  return <canvas ref={canvasRef} className="vrm-canvas" aria-hidden="true" />;
}
