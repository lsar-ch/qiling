#!/usr/bin/env python3
"""See-through 分层 PSD → DeskMate 角色资产包（逐层 PNG + layers.json）。

用法：
    python scripts/import_psd_layers.py <input.psd> <persona_id> [--out-dir DIR] [--anchor X Y]
    默认输出 data/persona-assets/<persona_id>/

依赖：pip install psd-tools（仅开发/生产工具，非运行时依赖）。
图层命名沿用 See-through 规范（face / front hair / irides / mouth ...），
导入时按 ROLE_MAP 打上 T4 动作角色标签（eyes / mouth / hair_front ...），
z 序取 PSD 文件内自底向上顺序，渲染器按 z 升序叠放。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image
from psd_tools import PSDImage

ROOT = Path(__file__).resolve().parents[1]

# See-through 图层名 → T4 动作角色（未列出的图层 role 为空，仅作静态叠放）
ROLE_MAP = {
    "irides": "eyes",
    "eyewhite": "eyes",
    "eyelash": "eyes",
    "eyebrow": "eyes",
    "mouth": "mouth",
    "front_hair": "hair_front",
    "back_hair": "hair_back",
    "face": "face",
    "nose": "face",
    "neck": "body",
    "ears": "body",
    "topwear": "body",
    "bottomwear": "body",
    "legwear": "body",
    "footwear": "body",
    "handwear": "body",
    "headwear": "accessory",
    "earwear": "accessory",
    "objects": "accessory",
    "tail": "tail",
    "wings": "wings",
}

# 与 assets/personas/default/layers.json 保持一致的默认动作映射
DEFAULT_MOTIONS = {
    "idle": {"css": "anim-breathe"},
    "listening": {"css": "anim-listen"},
    "thinking": {"css": "anim-think"},
    "speaking": {"css": "anim-talk"},
    "executing": {"css": "anim-run"},
    "awaiting_approval": {"css": "anim-wait"},
    "completed": {"css": "anim-done"},
    "interrupted": {"css": "anim-breathe"},
}


def import_psd(psd_path: Path, persona_id: str, out_dir: Path, anchor) -> dict:
    psd = PSDImage.open(psd_path)
    width, height = psd.size
    out_dir.mkdir(parents=True, exist_ok=True)
    layers_dir = out_dir / "layers"
    layers_dir.mkdir(exist_ok=True)

    layers_meta = []
    for z, layer in enumerate(psd):  # 迭代顺序 = 自底向上
        if not layer.visible:
            continue
        layer_id = layer.name.strip().lower().replace(" ", "_")
        img = layer.topil()
        if img is None:
            continue
        img = img.convert("RGBA")
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(img, (layer.left, layer.top), img)
        fname = f"{layer_id}.png"
        canvas.save(layers_dir / fname)
        layers_meta.append({
            "id": layer_id,
            "file": f"layers/{fname}",
            "z": z,
            "role": ROLE_MAP.get(layer_id, ""),
        })

    # 合成整图作为单图回退（main.png）
    comp = psd.composite(force=True)
    if comp is not None:
        comp.convert("RGBA").save(out_dir / "main.png")

    manifest = {
        "persona_id": persona_id,
        "version": 1,
        "source": "see_through_psd",
        "stage": {
            "width": width,
            "height": height,
            "anchor": list(anchor) if anchor else [width // 2, height // 2],
        },
        "layers": layers_meta,
        "motions": DEFAULT_MOTIONS,
    }
    (out_dir / "layers.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("psd", type=Path)
    parser.add_argument("persona_id")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--anchor", type=int, nargs=2, metavar=("X", "Y"), default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or ROOT / "data" / "persona-assets" / args.persona_id
    manifest = import_psd(args.psd, args.persona_id, out_dir, args.anchor)
    roles = {}
    for layer in manifest["layers"]:
        roles.setdefault(layer["role"] or "static", []).append(layer["id"])
    print(f"persona: {args.persona_id}  stage: {manifest['stage']}")
    print(f"layers: {len(manifest['layers'])} -> {out_dir}")
    for role, ids in sorted(roles.items()):
        print(f"  {role}: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
