#!/usr/bin/env node
// 校验 .vrma 结构：
//   1) VRMC_vrm_animation 扩展 + humanBones 是否等于动作库规范骨集。
//      规范骨名单在 scripts/vrm/humanoid-bones.json（与 normalize_vrma.py 共用同一份），
//      少了或多了一根都算 FAIL —— Blender 往返导出会按模型的人骨映射重建骨集，
//      静默丢 upperChest / 多出眼骨，只有这道校验能拦住。修复用 normalize_vrma.py。
//   2) VRMA 规范通道合法性：humanoid 骨不允许 scale；translation 只允许 hips。
//   3) in-place 检查：hips 水平位移必须归零。桌面桌宠的移动由桌面坐标系驱动，
//      片段自带水平位移会造成"双倍位移/漂移"，且不可在运行时补救。
//      竖直起伏（呼吸/步态 bob）允许，仅作信息输出。
//
// 用法:
//   node scripts/vrm/check_vrma.mjs <a.vrma> [b.vrma ...]
//   node scripts/vrm/check_vrma.mjs --hips-tol=0.03 <a.vrma>     # 放宽水平漂移阈值（米）
//   node scripts/vrm/check_vrma.mjs --allow-root-motion <a.vrma> # 显式跳过 in-place 检查
//   node scripts/vrm/check_vrma.mjs --verbose <a.vrma>           # 输出 hips 位移明细
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(path.join(here, "humanoid-bones.json"), "utf8"));
const CANONICAL = new Set(spec.bones);

// ---- 参数 ----
let hipsTol = 0.02; // 米。水平净位移超过即判 root motion
let allowRootMotion = false;
let verbose = false;
const files = [];
for (const arg of process.argv.slice(2)) {
  if (arg === "--allow-root-motion") allowRootMotion = true;
  else if (arg === "--verbose" || arg === "-v") verbose = true;
  else if (arg.startsWith("--hips-tol=")) {
    const v = Number(arg.slice("--hips-tol=".length));
    if (!Number.isFinite(v) || v < 0) {
      console.log(`参数错误: --hips-tol 需要非负数字（米），收到 ${arg}`);
      process.exit(2);
    }
    hipsTol = v;
  } else if (arg.startsWith("-")) {
    console.log(`未知参数: ${arg}`);
    process.exit(2);
  } else files.push(arg);
}

if (!files.length) {
  console.log("用法: node scripts/vrm/check_vrma.mjs [--hips-tol=0.02] [--allow-root-motion] [--verbose] <a.vrma> [...]");
  process.exit(2);
}

// ---- GLB 解析 ----
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;

function parseGlb(buf) {
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error("not a GLB file");
  let offset = 12;
  let json = null;
  let bin = null;
  while (offset + 8 <= buf.length) {
    const len = buf.readUInt32LE(offset);
    const type = buf.readUInt32LE(offset + 4);
    const data = buf.subarray(offset + 8, offset + 8 + len);
    if (type === CHUNK_JSON) json = JSON.parse(data.toString("utf8"));
    else if (type === CHUNK_BIN) bin = data;
    offset += 8 + len;
  }
  if (!json) throw new Error("GLB 缺少 JSON chunk");
  return { json, bin };
}

const COMPONENT_SIZE = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 };
const TYPE_COUNT = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

/** 读 float accessor，返回 [[x,y,z], ...]；不支持的类型返回 null（跳过而非误判） */
function readFloats(gltf, bin, accessorIndex) {
  const acc = gltf.accessors?.[accessorIndex];
  if (!acc || !bin) return null;
  if (acc.componentType !== 5126) return null; // 只处理 float
  if (acc.sparse) return null;
  const view = gltf.bufferViews?.[acc.bufferView];
  if (!view) return null;
  const n = TYPE_COUNT[acc.type] ?? 0;
  if (!n) return null;
  const size = COMPONENT_SIZE[acc.componentType];
  const stride = view.byteStride ?? n * size;
  const base = (view.byteOffset ?? 0) + (acc.byteOffset ?? 0);
  const out = [];
  for (let i = 0; i < acc.count; i++) {
    const p = base + i * stride;
    if (p + n * size > bin.length) return null;
    const v = new Array(n);
    for (let c = 0; c < n; c++) v[c] = bin.readFloatLE(p + c * size);
    out.push(v);
  }
  return out;
}

const mm = (m) => `${(m * 1000).toFixed(1)}mm`;

/** 返回 { issues: string[], info: string } */
function inspectChannels(gltf, bin) {
  const ext = gltf.extensions?.["VRMC_vrm_animation"];
  const bones = ext?.humanoid?.humanBones ?? {};
  const hipsNode = bones.hips?.node;
  const humanoidNodes = new Map(); // nodeIndex -> boneName
  for (const [name, v] of Object.entries(bones)) {
    if (v && typeof v.node === "number") humanoidNodes.set(v.node, name);
  }

  const issues = [];
  let hipsInfo = "no-hips-channel";

  for (const [ai, anim] of (gltf.animations ?? []).entries()) {
    for (const ch of anim.channels ?? []) {
      const node = ch.target?.node;
      const pathName = ch.target?.path;
      const boneName = humanoidNodes.get(node);
      if (!boneName) continue; // 非 humanoid 骨不在 VRMA 规范内，不参与校验

      if (pathName === "scale") {
        issues.push(`anim[${ai}] ${boneName} 有 scale 通道（VRMA 禁止 humanoid 骨缩放）`);
        continue;
      }
      if (pathName === "translation" && boneName !== "hips") {
        issues.push(`anim[${ai}] ${boneName} 有 translation 通道（VRMA 只允许 hips 平移）`);
        continue;
      }
      if (pathName !== "translation" || boneName !== "hips") continue;

      const sampler = anim.samplers?.[ch.sampler];
      const vals = sampler ? readFloats(gltf, bin, sampler.output) : null;
      if (!vals?.length) {
        hipsInfo = "hips-translation-unreadable";
        continue;
      }
      // glTF 是 Y-up：x/z 为水平面，y 为竖直
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      let minZ = Infinity, maxZ = -Infinity;
      for (const v of vals) {
        minX = Math.min(minX, v[0]); maxX = Math.max(maxX, v[0]);
        minY = Math.min(minY, v[1]); maxY = Math.max(maxY, v[1]);
        minZ = Math.min(minZ, v[2]); maxZ = Math.max(maxZ, v[2]);
      }
      const first = vals[0];
      const last = vals[vals.length - 1];
      const driftX = last[0] - first[0];
      const driftZ = last[2] - first[2];
      const drift = Math.hypot(driftX, driftZ);
      const yRange = maxY - minY;

      hipsInfo = `hips drift=${mm(drift)} y-range=${mm(yRange)} (${vals.length} keys)`;
      if (drift > hipsTol) {
        issues.push(
          `anim[${ai}] hips 水平净位移 ${mm(drift)} > 阈值 ${mm(hipsTol)}（疑似 root motion，运行时会双倍位移）`,
        );
      }
      if (verbose) {
        hipsInfo += ` x[${mm(minX)}..${mm(maxX)}] z[${mm(minZ)}..${mm(maxZ)}]`;
      }
    }
  }
  return { issues, info: hipsInfo };
}

// ---- 主循环 ----
let failed = 0;
let checked = 0;

for (const file of files) {
  checked++;
  try {
    const { json, bin } = parseGlb(readFileSync(file));
    const ext = json.extensions?.["VRMC_vrm_animation"];
    const bones = ext?.humanoid?.humanBones ?? {};
    const keys = Object.keys(bones);
    const missing = spec.bones.filter((name) => !keys.includes(name));
    const extra = keys.filter((name) => !CANONICAL.has(name)).sort();

    if (missing.length || extra.length) {
      console.log(`FAIL ${file}: humanBones=${keys.length}`);
      if (missing.length) console.log(`     缺失规范槽位: ${missing.join(", ")}`);
      if (extra.length) console.log(`     规范外槽位: ${extra.join(", ")}`);
      console.log("     修复: python3 scripts/vrm/normalize_vrma.py --source <源片段> <文件>");
      failed++;
      continue;
    }

    const { issues, info } = inspectChannels(json, bin);
    const rootMotionIssue = issues.filter((s) => s.includes("hips 水平净位移"));
    const blocking = allowRootMotion
      ? issues.filter((s) => !s.includes("hips 水平净位移"))
      : issues;

    if (blocking.length) {
      console.log(`FAIL ${file}: anims=${json.animations?.length ?? 0} humanBones=${keys.length} · ${info}`);
      for (const s of blocking) console.log(`     ${s}`);
      failed++;
      continue;
    }

    const tag = rootMotionIssue.length ? "root-motion(已豁免)" : "in-place";
    console.log(`OK ${file}: anims=${json.animations?.length ?? 0} humanBones=${keys.length} hips=${tag} · ${info}`);
  } catch (e) {
    console.log(`ERROR ${file}: ${e.message}`);
    failed++;
  }
}

if (checked > 1) console.log(`\n合计 ${checked} 个文件，${failed} 个未通过。`);
process.exit(failed ? 1 : 0);
