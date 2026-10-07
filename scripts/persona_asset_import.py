#!/usr/bin/env python3
"""栖灵 角色资产导入：基础形象 → 规范化透明立绘 + layers.json。

用法：
    python scripts/persona_asset_import.py <输入图片> <persona_id> [--out-dir 输出目录]

后台任务状态机（每个任务一个 JSON，落盘到 data/persona-tasks/）：
    python scripts/persona_asset_import.py --list-tasks
    python scripts/persona_asset_import.py --task-status TASK_ID
    python scripts/persona_asset_import.py --set-task-status TASK_ID STATUS [--result TEXT] [--error TEXT]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "ai-service"
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.persona_asset import normalize_avatar_file, png_bytes  # noqa: E402


TASKS_DIR = ROOT / "data" / "persona-tasks"

# 状态机：pending → running → completed / failed，后两者为终态。
TASK_STATUSES = ("pending", "running", "completed", "failed")
ALLOWED_TRANSITIONS = {
    "pending": ("running", "failed"),
    "running": ("completed", "failed"),
    "completed": (),
    "failed": (),
}
# 每类任务必须记录的参数：voice_clone = 参考音频 + 逐字文本 + 目标音色名。
REQUIRED_PARAMS = {
    "voice_clone": ("reference_audio", "transcript", "voice_name"),
    "avatar_import": ("input", "persona_id", "out_dir"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def write_task(task: dict) -> Path:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = task_path(task["task_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tmp.replace(path)


def load_task(task_id: str) -> dict | None:
    path = task_path(task_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def create_task(kind: str, params: dict, status: str = "pending") -> dict:
    if kind not in REQUIRED_PARAMS:
        raise ValueError(f"未知任务类型: {kind}")
    if status not in TASK_STATUSES:
        raise ValueError(f"非法任务状态: {status}")
    missing = [key for key in REQUIRED_PARAMS[kind] if not params.get(key)]
    if missing:
        raise ValueError(f"{kind} 任务缺少参数: {', '.join(missing)}")
    stamp = now_iso()
    task = {
        "task_id": f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "kind": kind,
        "status": status,
        "created_at": stamp,
        "updated_at": stamp,
        "params": params,
        "result": None,
        "error": None,
    }
    write_task(task)
    return task


def list_tasks(limit: int = 20) -> list[dict]:
    if not TASKS_DIR.is_dir():
        return []
    tasks = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        try:
            tasks.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            print(f"跳过无法解析的任务文件: {path.name}", file=sys.stderr)
    tasks.sort(key=lambda t: (t.get("created_at") or "", t.get("task_id") or ""), reverse=True)
    return tasks[:limit]


def set_task_status(
    task_id: str,
    status: str,
    result: str | None = None,
    error: str | None = None,
) -> dict:
    if status not in TASK_STATUSES:
        raise ValueError(f"非法任务状态: {status}（可选: {', '.join(TASK_STATUSES)}）")
    task = load_task(task_id)
    if task is None:
        raise KeyError(f"任务不存在: {task_id}")
    current = task["status"]
    if status != current and status not in ALLOWED_TRANSITIONS[current]:
        allowed = ", ".join(ALLOWED_TRANSITIONS[current]) or "无（终态）"
        raise ValueError(f"非法状态流转: {current} → {status}（{current} 可到: {allowed}）")
    task["status"] = status
    if result is not None:
        task["result"] = result
    if error is not None:
        task["error"] = error
    task["updated_at"] = now_iso()
    write_task(task)
    return task


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


def run_import(input_path: Path, persona_id: str, out_dir: Path | None) -> int:
    target = out_dir or (ROOT / "assets" / "personas" / persona_id)
    task = create_task(
        "avatar_import",
        {
            "input": str(input_path),
            "persona_id": persona_id,
            "out_dir": str(target),
            "output_size": None,
        },
        status="running",
    )
    print(f"任务 {task['task_id']} running")
    try:
        target.mkdir(parents=True, exist_ok=True)
        normalized = normalize_avatar_file(input_path)
        main_path = target / "main.png"
        main_path.write_bytes(png_bytes(normalized.image))
        layers = build_layers(persona_id, normalized.image.size, normalized.content_bbox)
        (target / "layers.json").write_text(
            json.dumps(layers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        set_task_status(task["task_id"], "failed", error=f"{type(exc).__name__}: {exc}")
        print(f"任务 {task['task_id']} failed: {exc}", file=sys.stderr)
        return 1

    task["params"]["output_size"] = [normalized.image.width, normalized.image.height]
    write_task(task)
    summary = (
        f"main.png {normalized.image.width}x{normalized.image.height} "
        f"processing={normalized.processing} bbox={list(normalized.content_bbox)} "
        f"anchor={layers['stage']['anchor']} -> {target}"
    )
    set_task_status(task["task_id"], "completed", result=summary)
    print(f"已写入 {main_path} ({normalized.image.width}x{normalized.image.height})")
    print(f"处理方式: {normalized.processing}")
    print(f"内容包围盒: {normalized.content_bbox}  锚点: {layers['stage']['anchor']}")
    print(f"已写入 {target / 'layers.json'}")
    print(f"任务 {task['task_id']} completed")
    return 0


def self_test() -> int:
    """状态机与 JSON 落盘自检（临时目录，不碰 data/）。"""
    global TASKS_DIR
    original = TASKS_DIR
    with tempfile.TemporaryDirectory() as tmp:
        TASKS_DIR = Path(tmp)
        try:
            voice = create_task(
                "voice_clone",
                {"reference_audio": "a.wav", "transcript": "你好", "voice_name": "moli"},
            )
            assert voice["status"] == "pending"
            assert load_task(voice["task_id"])["params"]["voice_name"] == "moli"
            try:
                create_task("voice_clone", {"reference_audio": "a.wav"})
                raise AssertionError("缺参数应当报错")
            except ValueError:
                pass

            task = create_task(
                "avatar_import", {"input": "i.png", "persona_id": "p", "out_dir": "o"}
            )
            set_task_status(task["task_id"], "running")
            done = set_task_status(task["task_id"], "completed", result="ok")
            assert done["status"] == "completed" and done["result"] == "ok"
            assert done["updated_at"] >= done["created_at"]
            for bad in ("pending", "running", "nope"):
                try:
                    set_task_status(task["task_id"], bad)
                    raise AssertionError(f"终态不应流转到 {bad}")
                except ValueError:
                    pass
            set_task_status(voice["task_id"], "failed", error="boom")
            assert load_task(voice["task_id"])["error"] == "boom"
            assert [t["task_id"] for t in list_tasks()] == [
                voice["task_id"],
                task["task_id"],
            ], "list_tasks 应按 created_at 倒序"
            assert [t["task_id"] for t in list_tasks(limit=1)] == [voice["task_id"]]
            assert load_task("missing") is None
        finally:
            TASKS_DIR = original
    print("self-test OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="PNG / JPG / WebP 基础形象")
    parser.add_argument("persona_id", nargs="?", help="角色 id（目录名）")
    parser.add_argument("--out-dir", type=Path, default=None, help="输出目录，默认 assets/personas/<id>")
    parser.add_argument("--list-tasks", action="store_true", help="列出最近任务")
    parser.add_argument("--task-status", metavar="TASK_ID", help="查询单个任务状态")
    parser.add_argument(
        "--set-task-status",
        nargs=2,
        metavar=("TASK_ID", "STATUS"),
        help=f"更新任务状态，可选: {', '.join(TASK_STATUSES)}",
    )
    parser.add_argument("--result", help="配合 --set-task-status 写入结果文本")
    parser.add_argument("--error", help="配合 --set-task-status 写入错误文本")
    parser.add_argument("--self-test", action="store_true", help="运行任务状态机自检")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.list_tasks:
        tasks = list_tasks()
        if not tasks:
            print("暂无任务记录")
            return 0
        for task in tasks:
            print(f"{task['created_at']}  {task['status']:<9}  {task['kind']:<13}  {task['task_id']}")
        return 0

    if args.task_status:
        task = load_task(args.task_status)
        if task is None:
            print(f"任务不存在: {args.task_status}", file=sys.stderr)
            return 1
        print(json.dumps(task, ensure_ascii=False, indent=2))
        return 0

    if args.set_task_status:
        task_id, status = args.set_task_status
        try:
            task = set_task_status(task_id, status, result=args.result, error=args.error)
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"{task['task_id']} → {task['status']}")
        return 0

    if args.input is None or args.persona_id is None:
        parser.error("需要 <输入图片> 和 <persona_id>，或使用 --list-tasks / --task-status / --set-task-status")
    return run_import(args.input, args.persona_id, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
