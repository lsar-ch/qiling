#!/usr/bin/env python3
"""组装随包分发的只读 home 模板（跨平台，替代 rsync 版 stage-home.sh）。

用法：python scripts/package/stage_home.py <输出目录>
Rust 首启时把模板整体拷到 Application Support / AppData。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PERSONA_IDS = ("default", "persona_2", "qiling")


def main(out: str) -> int:
    root = Path(__file__).resolve().parents[2]
    dst = Path(out)
    web_dist = root / "apps" / "web" / "dist"
    if not web_dist.is_dir():
        print("缺少 apps/web/dist，请先 npm run build", file=sys.stderr)
        return 1

    config_dst = dst / "config"
    config_dst.mkdir(parents=True, exist_ok=True)
    for item in (root / "config").iterdir():
        # agents.local.yaml 是用户运行时覆盖层，不随包分发
        if item.name == "agents.local.yaml":
            continue
        target = config_dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    shutil.copytree(web_dist, dst / "apps" / "web" / "dist", dirs_exist_ok=True)

    assets_dst = dst / "data" / "persona-assets"
    assets_dst.mkdir(parents=True, exist_ok=True)
    for persona_id in PERSONA_IDS:
        src = root / "data" / "persona-assets" / persona_id
        shutil.copytree(src, assets_dst / persona_id, dirs_exist_ok=True)
    (dst / "data" / "run").mkdir(parents=True, exist_ok=True)

    import yaml

    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    version = (settings or {}).get("app", {}).get("version", "0.1.0")
    (dst / ".seed-version").write_text(str(version), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
