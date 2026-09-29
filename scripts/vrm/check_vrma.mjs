#!/usr/bin/env node
// 校验 .vrma 结构：VRMC_vrm_animation 扩展 + humanBones 是否等于动作库规范骨集。
// 规范骨名单在 scripts/vrm/humanoid-bones.json（与 normalize_vrma.py 共用同一份），
// 少了或多了一根都算 FAIL —— Blender 往返导出会按模型的人骨映射重建骨集，
// 静默丢 upperChest / 多出眼骨，只有这道校验能拦住。修复用 normalize_vrma.py。
// 用法: node scripts/vrm/check_vrma.mjs <a.vrma> [b.vrma ...]
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(path.join(here, "humanoid-bones.json"), "utf8"));
const CANONICAL = new Set(spec.bones);

function parseGlb(buf) {
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error("not a GLB file");
  const jsonLen = buf.readUInt32LE(12);
  return JSON.parse(buf.toString("utf8", 20, 20 + jsonLen));
}

let failed = 0;
for (const file of process.argv.slice(2)) {
  try {
    const json = parseGlb(readFileSync(file));
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
    console.log(`OK ${file}: anims=${json.animations?.length ?? 0} humanBones=${keys.length}`);
  } catch (e) {
    console.log(`ERROR ${file}: ${e.message}`);
    failed++;
  }
}
process.exit(failed ? 1 : 0);
