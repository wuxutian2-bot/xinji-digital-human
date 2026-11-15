"""Measure real Breeze speech; use synthetic text only (non-commercial demos)."""

import argparse
import asyncio
import io
import json
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_llm_vtuber.tts.breeze_tts import (  # noqa: E402
    PREVIEW_TEXT,
    TTSEngine,
    build_instruction,
)


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    engine = TTSEngine(voice_id=args.voice_id, base_url=args.base_url, timeout=180)
    records = []
    if args.create_presets:
        existing = (await engine._request("GET", "/v1/voices")).json()
        protected = {"xinji_gentle", "xinji_bright"} & {v["id"] for v in existing}
        if protected:
            raise RuntimeError(
                "Refusing to overwrite existing reference voices: "
                + ", ".join(sorted(protected))
                + ". Run without --create-presets to test the saved voice."
            )
        # Exact synthetic transcript avoids guessing a crop's spoken words.
        for name, description, seed in (
            (
                "xinji_gentle",
                "年轻成年女性的中文声音，温柔自然、清晰柔和，像一位耐心的朋友，语速适中",
                42,
            ),
            (
                "xinji_bright",
                "年轻成年女性的中文声音，清亮自然、轻快有活力，亲切明朗，语速适中",
                43,
            ),
        ):
            start = time.perf_counter()
            wav = await engine.synthesize_wav(
                PREVIEW_TEXT, voice_id="", instruction=description, seed=seed
            )
            with wave.open(io.BytesIO(wav)) as audio:
                duration = audio.getnframes() / audio.getframerate()
            if not 5 <= duration <= 15:
                raise RuntimeError(
                    f"{name}: reference is {duration:.2f}s; expected 5–15s"
                )
            (args.output / f"{name}_reference.wav").write_bytes(wav)
            await engine.register_voice(name, wav)
            record = dict(
                voice_id=name,
                description=description,
                seed=seed,
                ref_text=PREVIEW_TEXT,
                audio_seconds=duration,
                elapsed_seconds=time.perf_counter() - start,
            )
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    for style, text, speed, energy in (
        ("calm", "今天愿意来聊聊，就已经很好了。", 1.0, 1.0),
        ("warm", "听起来你有些难过，我们可以慢慢说。", 0.85, 0.8),
        ("steady", "先照顾好眼前的自己，我会陪你一步一步来。", 0.85, 1.0),
    ):
        first = None
        start = time.perf_counter()
        fields = engine._fields(
            text,
            instruction=build_instruction(
                engine.base_instruction, style, speed, energy
            ),
        )
        async with engine._generation_slot(), engine._async_client() as client:
            async with client.stream(
                "POST", "/v1/audio/speech", data=fields
            ) as response:
                response.raise_for_status()
                chunks = []
                async for chunk in response.aiter_bytes():
                    if chunk and first is None:
                        first = time.perf_counter() - start
                    chunks.append(chunk)
        from open_llm_vtuber.tts.breeze_tts import pcm_to_wav

        wav = pcm_to_wav(b"".join(chunks))
        elapsed = time.perf_counter() - start
        with wave.open(io.BytesIO(wav)) as audio:
            duration = audio.getnframes() / audio.getframerate()
        (args.output / f"{style}.wav").write_bytes(wav)
        record = dict(
            style=style,
            voice_id=args.voice_id,
            first_pcm_seconds=first,
            elapsed_seconds=elapsed,
            audio_seconds=duration,
            realtime_factor=duration / elapsed,
        )
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    (args.output / "report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--voice-id", default="xinji_bright")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/breeze_smoke")
    parser.add_argument(
        "--create-presets",
        action="store_true",
        help="Generate and save the two synthetic reference voices",
    )
    asyncio.run(main(parser.parse_args()))
