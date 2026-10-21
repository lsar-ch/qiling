import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";

const assetUrl = (personaId: string, file: string): string =>
  `/api/personas/${encodeURIComponent(personaId)}/asset/${file.split("/").map(encodeURIComponent).join("/")}`;
const libraryUrl = (variant: string, file: string): string =>
  `/api/motion-library/${encodeURIComponent(variant)}/${file.split("/").map(encodeURIComponent).join("/")}`;

interface Props {
  personaId: string;
  /** 共享动作库（male / female）：配了优先从库里取 VRMA。 */
  library?: string;
  trigger: string;
  /** VRMA 文件基名。缺省同 trigger；配了 vrm.actions 映射时传映射后的文件名。 */
  clipBase?: string;
  loop: boolean;
  crossfadeMs?: number;
}

/** 动作实验室的 3D VRMA 预览：加载 model.vrm + 单个 trigger 的 VRMA 循环播放。 */
export default function VrmPreview({ personaId, library, trigger, clipBase, loop, crossfadeMs = 200 }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let disposed = false;
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(28, mount.clientWidth / mount.clientHeight, 0.1, 50);

    const fitCamera = (vrm: any): void => {
      const box = new THREE.Box3().setFromObject(vrm.scene);
      const head = vrm.humanoid?.getNormalizedBoneNode("head");
      const foot =
        vrm.humanoid?.getNormalizedBoneNode("leftFoot") ??
        vrm.humanoid?.getNormalizedBoneNode("rightFoot");
      const headY = head ? head.getWorldPosition(new THREE.Vector3()).y : box.max.y;
      const footY = foot ? foot.getWorldPosition(new THREE.Vector3()).y : box.min.y;
      const height = Math.max(0.1, headY - footY);
      const targetY = headY - height * 0.42;
      const distance = Math.max((height / 2 / Math.tan((camera.fov * Math.PI) / 360)) * 1.35, 0.8);
      camera.position.set(0, targetY, distance);
      camera.lookAt(0, targetY, 0);
    };

    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.4));
    const dir = new THREE.DirectionalLight(0xffffff, 1.2);
    dir.position.set(1, 2, 1);
    scene.add(dir);

    const mixer = new THREE.AnimationMixer(scene);
    let current: THREE.AnimationAction | null = null;
    let clipCache: THREE.AnimationClip | null = null;

    const playClip = (clip: THREE.AnimationClip | null): void => {
      if (!clip) return;
      const action = mixer.clipAction(clip);
      action.reset();
      action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
      action.play();
      if (current && current !== action) current.crossFadeTo(action, crossfadeMs / 1000, false);
      current = action;
    };

    let raf = 0;
    const clock = new THREE.Clock();
    let vrm: any = null;
    const tick = (): void => {
      const delta = clock.getDelta();
      mixer.update(delta);
      // 必须调 vrm.update()：VRMA 只写 normalized 骨，网格实际跟 raw 骨，
      // 漏掉这一步会永远停在 T-pose（真实挂件 VrmStage 有调）
      vrm?.update(delta);
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();

    (async () => {
      try {
        const vrmRes = await fetch(assetUrl(personaId, "model.vrm"));
        if (!vrmRes.ok || disposed) return;
        const vrmLoader = new GLTFLoader();
        vrmLoader.register((parser) => new VRMLoaderPlugin(parser));
        const vrmGltf = await vrmLoader.parseAsync(await vrmRes.arrayBuffer(), "");
        vrm = vrmGltf.userData.vrm;
        if (!vrm) return;
        vrm.scene.traverse((o: THREE.Object3D) => { o.frustumCulled = false; });
        scene.add(vrm.scene);
        fitCamera(vrm);

        const clipName = `${clipBase || trigger}.vrma`;
        const shared = library ? await fetch(libraryUrl(library, clipName)) : null;
        const vrmaRes = shared?.ok ? shared : await fetch(assetUrl(personaId, `vrma/${clipName}`));
        if (!vrmaRes.ok || disposed) return;
        const loader = new GLTFLoader();
        loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
        const g = await loader.parseAsync(await vrmaRes.arrayBuffer(), "");
        const anims = g.userData.vrmAnimations;
        if (!anims?.length) return;
        clipCache = createVRMAnimationClip(anims[0], vrm);
        playClip(clipCache);
      } catch {
        // 加载失败静默，保留空画布。
      }
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
    };
  }, [personaId, library, trigger, clipBase, loop, crossfadeMs]);

  return <div ref={mountRef} className="h-64 w-full rounded-lg bg-ink/5" />;
}
