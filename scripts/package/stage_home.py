#!/usr/bin/env python3
"""组装随包分发的只读 home 模板（跨平台，替代 rsync 版 stage-home.sh）。

用法：python scripts/package/stage_home.py <输出目录>
Rust 首启时把模板整体拷到 Application Support / AppData。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Windows 控制台默认 cp1252，无法编码中文；统一切到 UTF-8，
# 否则打包脚本会在 CI 上因 print 中文而中断（2026-10-22 Windows 构建回归）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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

    # 动作库**随包分发**（方案 B，2026-10-21 决策）。理由：不含动作库时安装后只剩
    # 程序化待机（沉肩垂臂 + 呼吸 + 眨眼），用户装完看到的是没动作的角色，体验不完整。
    #
    # 授权口径（必须随源码保留，见 NOTICE / docs/MIXAMO-LICENSE-2026-10-11.md）：
    #   data/motion-library 下的 .vrma 为「Mixamo 参考片派生」动作——逐帧采样参考片骨骼
    #   旋转后重定向到本项目 VRM 骨架并做幅度调整，非 Mixamo 原始文件，但属衍生作品。
    #   随包分发时须保留“动作由 Mixamo 参考片派生”的声明与 Mixamo 使用条款链接。
    #
    # CI/干净环境无此目录时自动跳过（installer 退化为程序化待机）。
    # 需要出「无动作资产」包时显式排除：QILING_STAGE_NO_MOTION_LIB=1
    import os

    motion_src = root / "data" / "motion-library"
    if os.environ.get("QILING_STAGE_NO_MOTION_LIB") == "1":
        print("· 已按 QILING_STAGE_NO_MOTION_LIB=1 跳过动作库（安装后退化为程序化待机）")
    elif motion_src.is_dir():
        shutil.copytree(motion_src, dst / "data" / "motion-library", dirs_exist_ok=True)
        n = len(list((dst / "data" / "motion-library").rglob("*.vrma")))
        print(f"· 动作库已入包：{n} 个 .vrma（Mixamo 参考片派生，声明见 NOTICE）")
        notice = root / "NOTICE"
        if notice.is_file():
            shutil.copy2(notice, dst / "NOTICE")

    import yaml

    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    version = (settings or {}).get("app", {}).get("version", "0.1.0")
    (dst / ".seed-version").write_text(str(version), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
