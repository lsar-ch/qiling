#!/usr/bin/env python3
"""DeskMate 音色试听验收脚本（需真实 DASHSCOPE_API_KEY）。

用法：
  # 1) 合成一组预置音色 + 固定词表，输出到 data/voice_samples/<voice>/*.wav
  .venv/bin/python scripts/voice_probe.py \
      --voices longxiaochun_v2,longxiaoxia_v2,longjing_v2

  # 2) （可选）先用参考音频注册克隆音色，再把它加入 --voices 对比
  .venv/bin/python scripts/voice_probe.py --enroll "https://example.com/ref.wav" \
      --voices <返回的voice_id>,longxiaochun_v2

  # 3) （可选）顺手验证一次 STT：用你录的 16k 单声道 wav
  .venv/bin/python scripts/voice_probe.py --stt /path/to/input.wav

词表覆盖日常/卖萌/冷静/任务完成/台味示例，便于同一句子并排 A/B 听感打分。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-service"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "contracts" / "py"))

SAMPLE_SENTENCES: dict[str, str] = {
    "00-greet": "你好呀，我是 DeskMate，今天想让我帮你做点什么呢？",
    "01-cute": "诶～这个任务有点意思，交给我你放心啦！",
    "02-calm": "收到，我先梳理一下步骤，稍等片刻，有结果马上告诉你。",
    "03-done": "搞定啦！已经把结果整理好放到主界面咯。",
    "04-taiwan-flavor": "那个呀，我觉得可以这样弄，超简单的，我帮你处理一下喔。",
}


def _load_settings() -> object:
    from app.config import load_settings

    settings = load_settings()
    return settings



async def _synth_with_retry(synth, text, params, attempts: int = 3):
    """云合成偶发超时，简单重试。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await synth.synthesize(text, params=params)
        except Exception as exc:  # noqa: BLE001 - 网络偶发需要重试
            last = exc
            await asyncio.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]

async def _synth_batch(settings, voices: list[str]) -> list[Path]:
    from deskmate_contracts.voice import VoiceParams
    from app.speech.dashscope import DashScopeSynthesizer

    base = settings.repo_root / "data" / "voice_samples"
    out_paths: list[Path] = []
    for voice in voices:
        synth = DashScopeSynthesizer(
            api_key=settings.dashscope_api_key or "",
            model=settings.tts_model,
            voice=voice,
            fmt="wav",
            sample_rate=24000,
            defaults=VoiceParams(speed=1.05, pitch=1.0, volume=1.0),
        )
        voice_dir = base / voice
        voice_dir.mkdir(parents=True, exist_ok=True)
        for label, text in SAMPLE_SENTENCES.items():
            result = await _synth_with_retry(synth, text, VoiceParams(voice=voice, speed=1.05))
            target = voice_dir / f"{label}.wav"
            target.write_bytes(result.data)
            out_paths.append(target)
        print(f"✔ {voice}: {len(SAMPLE_SENTENCES)} 段已输出 → {voice_dir}")
    return out_paths


def _enroll(settings, url: str) -> str:
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    import dashscope

    dashscope.api_key = settings.dashscope_api_key or ""
    service = VoiceEnrollmentService()
    voice_id = service.create_voice(url=url)
    print(f"✔ 克隆音色已创建：{voice_id}")
    return voice_id



async def _synth_tones(settings) -> None:
    """按校准目录把每个情绪用载句 + 自然句各合成一段，供语气 A/B。"""
    from deskmate_contracts.voice import VoiceParams
    from app.speech.dashscope import DashScopeSynthesizer
    from app.speech.tone_catalog import load_validated

    catalog = load_validated(settings.repo_root)
    synth = DashScopeSynthesizer(
        api_key=settings.dashscope_api_key or "",
        model=settings.tts_model,
        voice=settings.tts_voice,
        fmt="wav",
        sample_rate=24000,
    )
    out_dir = settings.repo_root / "data" / "voice_samples" / "tones"
    out_dir.mkdir(parents=True, exist_ok=True)
    carrier = catalog["carrier_sentence"]
    for key, item in catalog["emotions"].items():
        params = VoiceParams(
            voice=settings.tts_voice,
            speed=item["params"]["speed"],
            pitch=item["params"]["pitch"],
            volume=item["params"]["volume"],
            instruction=item["dashscope"].get("instruction"),
        )
        carrier_data = await _synth_with_retry(synth, carrier, params)
        (out_dir / f"{key}-carrier.wav").write_bytes(carrier_data.data)
        natural_data = await _synth_with_retry(synth, item["test_sentence_zh"], params)
        (out_dir / f"{key}-natural.wav").write_bytes(natural_data.data)
        tag = params.instruction or "(默认语气)"
        print(f"✔ {key:10s}  {tag}")
    print(f"\n情绪试听目录：{out_dir}（先听 -carrier 对比声音，再听 -natural 对比语气）")


def _stt_check(settings, wav_path: str) -> None:
    from app.speech.dashscope import DashScopeRecognizer

    recognizer = DashScopeRecognizer(
        api_key=settings.dashscope_api_key or "",
        model=settings.stt_model,
        sample_rate=settings.stt_sample_rate,
    )
    text = asyncio.run(recognizer.recognize(wav_path, settings.stt_language))
    print(f"✔ STT 结果：{text or '（空，未识别到内容）'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", default="longxiaochun_v2,longxiaoxia_v2,longjing_v2")
    parser.add_argument("--enroll", default=None, help="注册克隆音色的参考音频 URL")
    parser.add_argument("--stt", default=None, help="用本地 wav 验证一次语音识别")
    parser.add_argument("--tones", action="store_true", help="按校准目录合成各情绪的载句+自然句，做语气 A/B")
    args = parser.parse_args()

    settings = _load_settings()
    if not settings.dashscope_api_key:
        print("尚未配置 DASHSCOPE_API_KEY。请先：")
        print("  1) 在阿里云百炼控制台开通 CosyVoice/Paraformer 并创建 API Key")
        print("  2) 写入 .env 或导出环境变量 DASHSCOPE_API_KEY")
        print("  3) 重启 ai-service 后重跑本脚本")
        return 2

    voices = [v.strip() for v in args.voices.split(",") if v.strip()]

    if args.enroll:
        created = _enroll(settings, args.enroll)
        if created not in voices:
            voices.append(created)

    if voices:
        asyncio.run(_synth_batch(settings, voices))
        print(f"\n试听目录：{settings.repo_root / 'data' / 'voice_samples'}")
        print("建议：同一句话各音色并排试听，按「台味/亲切感/自然度/稳定性」1-5 打分。")

    if args.tones:
        asyncio.run(_synth_tones(settings))

    if args.stt:
        _stt_check(settings, args.stt)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
