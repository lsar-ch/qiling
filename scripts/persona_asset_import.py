#!/usr/bin/env python3
"""DeskMate 角色资产导入：基础形象 → 规范化透明立绘 + layers.json。

用法：
    python scripts/persona_asset_import.py <输入图片> <persona_id> [--out-dir 输出目录]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "ai-service"
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.persona_asset import normalize_avatar_file, png_bytes  # noqa: E402


def build_layers(
    persona_id: str,
    size: tuple[int, int],
    bbox: tuple[int, int, int, int],
) -> dict:
    x0, y0, x1, y1 = bbox
    return {
        "persona_id": persona_id,
        "version": 1,
        "stage": {
            "width": size[0],
            "height": size[1],
            "anchor": [(x0 + x1) // 2, y1],
        },
        "layers": [{"id": "body", "file": "main.png", "z": 0}],
        "motions": {
            "idle": {"css": "anim-breathe"},
            "listening": {"css": "anim-listen"},
            "thinking": {"css": "anim-think"},
            "speaking": {"css": "anim-talk"},
            "executing": {"css": "anim-run"},
            "awaiting_approval": {"css": "anim-wait"},
            "completed": {"css": "anim-done"},
            "interrupted": {"css": "anim-breathe"},
        },
        "theme": {"primary": "#6366F1", "aura": "#818CF8", "accent": "#C4B5FD"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PNG / JPG / WebP 基础形象")
    parser.add_argument("persona_id", help="角色 id（目录名）")
    parser.add_argument("--out-dir", type=Path, default=None, help="输出目录，默认 assets/personas/<id>")
    args = parser.parse_args()

    out_dir = args.out_dir or (
        Path(__file__).resolve().parents[1] / "assets" / "personas" / args.persona_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized = normalize_avatar_file(args.input)
    main_path = out_dir / "main.png"
    main_path.write_bytes(png_bytes(normalized.image))
    layers = build_layers(args.persona_id, normalized.image.size, normalized.content_bbox)
    (out_dir / "layers.json").write_text(
        json.dumps(layers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已写入 {main_path} ({normalized.image.width}x{normalized.image.height})")
    print(f"处理方式: {normalized.processing}")
    print(f"内容包围盒: {normalized.content_bbox}  锚点: {layers['stage']['anchor']}")
    print(f"已写入 {out_dir / 'layers.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
