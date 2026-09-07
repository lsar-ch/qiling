#!/usr/bin/env python3
"""MiniMax Speech 试听脚本（speech-2.8-hd，支持 emotion 参数）。

用法：
  .venv/bin/python scripts/probe_minimax.py                 # 列出中文音色
  .venv/bin/python scripts/probe_minimax.py --voices "Chinese (Mandarin)_Sweet_Lady" --emotions neutral,happy,sad,calm
  .venv/bin/python scripts/probe_minimax.py --text "自定义文案" --emotions whisper,surprised
  .venv/bin/python scripts/probe_minimax.py --clone <音频文件> --voice-id deskmate_voice_01
  .venv/bin/python scripts/probe_minimax.py --list-cloned     # 列出已克隆音色

说明：
  - Key 从项目根 .env 的 MINIMAX_API_KEY 读取；
  - 音频输出到 data/voice_samples/minimax/<voice>/<emotion>-<n>.mp3；
  - 克隆输出到 data/voice_samples/cloned/；克隆本身 + 首次使用计费；
  - emotion 取值参考：happy, sad, angry, fearful, disgusted, surprised, calm, fluent, whisper。
"""

from __future__ import annotations

import argparse
import binascii
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.minimaxi.com/v1"
DEFAULT_VOICES = [
    "Chinese (Mandarin)_Sweet_Lady",
    "Chinese (Mandarin)_Warm_Girl",
    "Chinese (Mandarin)_Soft_Girl",
]


def _key() -> str:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    import os

    key = os.environ.get("MINIMAX_API_KEY", "")
    if not key:
        raise SystemExit("未找到 MINIMAX_API_KEY，请写入项目根 .env")
    return key


def list_voices(headers: dict) -> list[dict]:
    resp = httpx.post(f"{API}/get_voice", json={"voice_type": "system"}, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("base_resp", {}).get("status_code") not in (0, None):
        raise SystemExit(f"获取音色失败：{data.get('base_resp')}")
    return data.get("system_voice") or []


def list_cloned_voices(headers: dict) -> list[dict]:
    resp = httpx.post(f"{API}/get_voice", json={"voice_type": "voice_cloning"}, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("base_resp", {}).get("status_code") not in (0, None):
        raise SystemExit(f"获取克隆音色失败：{data.get('base_resp')}")
    return data.get("voice_cloning") or []


def upload_for_clone(headers: dict, path: Path) -> str:
    with path.open("rb") as f:
        resp = httpx.post(
            f"{API}/files/upload",
            headers=headers,
            files={"file": (path.name, f, "application/octet-stream")},
            data={"purpose": "voice_clone"},
            timeout=120,
        )
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code") != 0:
        raise RuntimeError(f"上传失败：{base}")
    file_id = (data.get("file") or {}).get("file_id")
    if not file_id:
        raise RuntimeError(f"上传响应缺少 file_id：{data}")
    return file_id


def clone_voice(headers: dict, file_id: str, voice_id: str, demo_text: str | None) -> str | None:
    payload = {"file_id": file_id, "voice_id": voice_id}
    if demo_text:
        payload.update({"text": demo_text, "model": "speech-2.8-hd"})
    resp = httpx.post(f"{API}/voice_clone", json=payload, headers=headers, timeout=180)
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code") != 0:
        raise RuntimeError(f"克隆失败：{base}")
    return data.get("demo_audio")


def synthesize(headers: dict, voice: str, text: str, emotion: str | None, speed: float) -> bytes:
    body = {
        "model": "speech-2.8-hd",
        "text": text,
        "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1, "pitch": 0},
        "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000, "channel": 1},
        "output_format": "hex",
    }
    if emotion:
        body["voice_setting"]["emotion"] = emotion
    resp = httpx.post(f"{API}/t2a_v2", json=body, headers=headers, timeout=120)
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code") != 0:
        raise RuntimeError(f"合成失败：{base}")
    audio = (data.get("data") or {}).get("audio")
    if not audio:
        raise RuntimeError("响应缺少 audio")
    return binascii.unhexlify(audio)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", default=",".join(DEFAULT_VOICES))
    parser.add_argument("--emotions", default="neutral,happy,sad,calm,whisper")
    parser.add_argument("--text", default="我把这件事处理好了，你听看看情绪差别是不是很清楚。")
    parser.add_argument("--speed", type=float, default=1.05)
    parser.add_argument("--list", action="store_true", help="只列出中文音色")
    parser.add_argument("--list-cloned", action="store_true", help="只列出已克隆音色")
    parser.add_argument("--clone", metavar="FILE", help="用一段音频克隆新音色（先上传素材再克隆）")
    parser.add_argument("--voice-id", default="deskmate_voice_01", help="克隆音色的 voice_id")
    parser.add_argument("--demo-text", default="你好，我是你的桌面小助手，这段声音是我刚克隆出来的。")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {_key()}"}

    if args.list_cloned:
        for v in list_cloned_voices(headers):
            print(f"{v.get('voice_id')}  |  {(v.get('voice_name') or v.get('voice_id'))}")
        return 0

    if args.clone:
        src = Path(args.clone)
        if not src.exists():
            raise SystemExit(f"文件不存在：{src}")
        print(f"① 上传素材：{src.name}（{src.stat().st_size / 1024:.0f} KB）")
        file_id = upload_for_clone(headers, src)
        print(f"   上传成功 file_id={file_id}")
        print(f"② 发起克隆 voice_id={args.voice_id} ...")
        demo_url = clone_voice(headers, file_id, args.voice_id, args.demo_text)
        out_dir = ROOT / "data" / "voice_samples" / "cloned"
        out_dir.mkdir(parents=True, exist_ok=True)
        if demo_url:
            suffix = Path(demo_url.split("?")[0]).suffix or ".mp3"
            demo_path = out_dir / f"{args.voice_id}_demo{suffix}"
            demo_path.write_bytes(httpx.get(demo_url, timeout=120).content)
            print(f"③ 试听音频已保存：{demo_path}")
        print("④ 刷新克隆音色列表 ...")
        time.sleep(2)
        cloned = {v.get("voice_id") for v in list_cloned_voices(headers)}
        if args.voice_id in cloned:
            print(f"   ✔ {args.voice_id} 已在 voice_cloning 列表中")
        else:
            print("   ⚠ 列表暂未出现，可能还在构建，稍后重试 --list-cloned 确认")
        return 0

    voices = list_voices(headers)
    if args.list:
        for v in voices:
            vid = v.get("voice_id", "")
            if vid.lower().startswith("chinese"):
                desc = " ".join(v.get("voice_desc") or [])
                print(f"{vid}  |  {(v.get('voice_name') or '')}  |  {desc[:70]}")
        return 0

    emotions = [e.strip() for e in args.emotions.split(",") if e.strip()]
    out_root = ROOT / "data" / "voice_samples" / "minimax"
    for voice in [v.strip() for v in args.voices.split(",") if v.strip()]:
        if voice not in {v.get("voice_id") for v in voices}:
            print(f"⚠ 未知音色，跳过：{voice}")
            continue
        out_dir = out_root / voice.replace(" ", "_").replace("(", "").replace(")", "")
        out_dir.mkdir(parents=True, exist_ok=True)
        for emotion in emotions:
            try:
                audio = synthesize(headers, voice, args.text, None if emotion == "neutral" else emotion, args.speed)
                target = out_dir / f"{emotion}.mp3"
                target.write_bytes(audio)
                print(f"✔ {voice.split('_')[-1]:16s}  {emotion:10s} -> {target}")
            except Exception as exc:  # noqa: BLE001
                print(f"✘ {voice.split('_')[-1]:16s}  {emotion:10s}  失败：{exc}")
    print(f"\n试听目录：{out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
