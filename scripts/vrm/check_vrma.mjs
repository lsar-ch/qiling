#!/usr/bin/env node
// 校验 .vrma 结构：VRMC_vrm_animation 扩展 + humanBones 的 key 是否为 VRM 标准名。
// 用法: node scripts/vrm/check_vrma.mjs <a.vrma> [b.vrma ...]
import { readFileSync } from "node:fs";

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
    const ok = keys.includes("hips") && keys.includes("head");
    if (!ok) {
      console.log(`FAIL ${file}: humanBones=${keys.length} keys=[${keys.join(",")}]`);
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
