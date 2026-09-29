// node 环境没有 DOM 图片解码器，给 GLTFLoader 打最小桩，只验结构与表情
globalThis.self = globalThis;
globalThis.Image = class {
  constructor() { this.width = 1; this.height = 1; }
  set src(_v) { setTimeout(() => this.onload && this.onload(), 0); }
};
if (!globalThis.URL.createObjectURL) {
  globalThis.URL.createObjectURL = () => "blob:stub";
  globalThis.URL.revokeObjectURL = () => {};
}
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import fs from "node:fs";

const file = process.argv[2];
THREE.Cache.enabled = false;
const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
const buf = fs.readFileSync(file);
const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const gltf = await loader.parseAsync(arr, "");
const vrm = gltf.userData.vrm;
if (!vrm) { console.log("FAIL: 不是可被 three-vrm 解析的 VRM"); process.exit(1); }
VRMUtils.rotateVRM0(vrm);
console.log("meta.name:", vrm.meta?.name);
console.log("meta.title:", vrm.meta?.title);
const NEED = ["aa","ih","ou","ee","oh","blink","happy","angry","sad","relaxed","neutral","lookUp","lookDown","lookLeft","lookRight"];
const presets = Object.keys(vrm.expressionManager?.presetExpressionMap ?? {});
console.log("presetExpressionMap:", JSON.stringify(presets.sort()));
const missing = NEED.filter((n) => !presets.includes(n));
console.log(missing.length ? "FAIL missing expressions: " + missing : "OK 15 表情齐全");
for (const name of NEED) {
  const def = vrm.expressionManager.getExpression(name);
  // neutral 就是 rest 状态，VRM 1.0 允许空绑定；其余表情必须有 bind
  const ok = !!def && (name === "neutral" || (def.binds?.length ?? 0) > 0);
  console.log(`  ${ok ? "OK  " : "BAD "} ${name.padEnd(10)} isBinary=${def?.isBinary} binds=${def?.binds?.length}`);
}
// 实际驱动一遍，确认 setValue 不抛错且权重生效
const em = vrm.expressionManager;
for (const name of NEED) {
  em.setValue(name, 1.0);
  if (Math.abs((em.getValue(name) ?? 0) - 1.0) > 1e-6) {
    console.log(`  WARN ${name} setValue(1) -> ${em.getValue(name)}`);
  }
  em.setValue(name, 0.0);
}
em.update();
console.log("OK setValue/update 无异常");
// upperChest 是 VRM1 可选骨，VrmStage 渲染链不引用，缺了只提示，不算失败。
const bones = ["hips","spine","chest","neck","head","leftUpperArm","rightUpperArm","leftHand","rightHand","leftUpperLeg","leftLowerLeg","leftFoot","rightFoot"];
const bad = bones.filter((b) => !vrm.humanoid?.getNormalizedBoneNode(b));
console.log(bad.length ? "FAIL humanoid missing: " + bad : "OK humanoid 13 关键骨齐全");
if (!vrm.humanoid?.getNormalizedBoneNode("upperChest")) {
  console.log("  WARN upperChest 缺失（VRM1 可选骨，渲染链不引用）");
}
const box = new THREE.Box3().setFromObject(vrm.scene);
const size = new THREE.Vector3(); box.getSize(size);
console.log("bbox size(m):", size.x.toFixed(3), size.y.toFixed(3), size.z.toFixed(3));
const head = vrm.humanoid.getNormalizedBoneNode("head");
const foot = vrm.humanoid.getNormalizedBoneNode("leftFoot");
const hp = head.getWorldPosition(new THREE.Vector3());
const fp = foot.getWorldPosition(new THREE.Vector3());
console.log("head-feet height(m):", (hp.y - fp.y).toFixed(3));
let tris = 0, mats = new Set();
vrm.scene.traverse((o) => { if (o.isMesh && o.geometry?.index) { tris += o.geometry.index.count / 3; (Array.isArray(o.material)?o.material:[o.material]).forEach(m=>mats.add(m.uuid)); }});
console.log("runtime tris:", tris, "materials:", mats.size);
console.log("expressions total:", vrm.expressionManager?.expressions?.length);
console.log("\nRESULT:", missing.length === 0 && bad.length === 0 ? "PASS" : "FAIL");
