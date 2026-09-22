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
import { personaAssetUrl, type ExpressionEmotion } from "../api";
import type { ActionTrigger } from "./actions";
import { lipSyncBus } from "./lipSync";

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
  /** 首帧渲染就绪（占位图可撤）时回调 */
  onReady?: () => void;
}

interface Rig {
  vrm: VRM;
  mixer: THREE.AnimationMixer;
  play: (trigger: ActionTrigger) => Promise<void>;
}

export default function VrmStage({ personaId, vrmPath, trigger, emotion, onReady }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rigRef = useRef<Rig | null>(null);
  const triggerRef = useRef<ActionTrigger>(trigger);
  const emotionRef = useRef<ExpressionEmotion>(emotion);
  triggerRef.current = trigger;
  emotionRef.current = emotion;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let raf = 0;

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
      VRMUtils.combineSkeletons(vrm.scene);
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
      const clips = new Map<ActionTrigger, THREE.AnimationClip | null>();
      let current: THREE.AnimationAction | null = null;

      const ensureClip = async (name: ActionTrigger): Promise<THREE.AnimationClip | null> => {
        if (clips.has(name)) return clips.get(name) ?? null;
        clips.set(name, null); // 占位防重复加载；404 即视为缺失
        try {
          const r = await fetch(personaAssetUrl(personaId, `vrma/${name}.vrma`));
          if (!r.ok) return null;
          const g = await vrmaLoader.parseAsync(await r.arrayBuffer(), "");
          const anims = g.userData.vrmAnimations as
            | Parameters<typeof createVRMAnimationClip>[0][]
            | undefined;
          if (!anims?.length) return null;
          const clip = createVRMAnimationClip(anims[0], vrm);
          clips.set(name, clip);
          return clip;
        } catch {
          return null;
        }
      };

      const play = async (name: ActionTrigger): Promise<void> => {
        const clip = await ensureClip(name);
        if (disposed || !clip) return; // 缺片段静默保持当前动作
        const action = mixer.clipAction(clip, vrm.scene);
        action.reset();
        if (LOOP_TRIGGERS.has(name)) action.setLoop(THREE.LoopPingPong, Infinity);
        else action.setLoop(THREE.LoopOnce, 1);
        action.play();
        if (current && current !== action) current.crossFadeTo(action, CROSSFADE_S, false);
        current = action;
      };

      mixer.addEventListener("finished", () => {
        void play("idle"); // 一次性动作播完回 idle
      });

      rigRef.current = { vrm, mixer, play };
      await play(triggerRef.current);
      if (disposed) return;
      // 显示前先推一帧，避免闪 bind pose
      vrm.update(0);
      mixer.update(0);
      scene.visible = true;
      onReady?.();

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
      rigRef.current = null;
      renderer.dispose();
    };
  }, [personaId, vrmPath, onReady]);

  // trigger 变化 → 切换动作（加载完成前的 trigger 由 setup 内的首播兜底）
  useEffect(() => {
    void rigRef.current?.play(trigger);
  }, [trigger]);

  return <canvas ref={canvasRef} className="vrm-canvas" aria-hidden="true" />;
}
