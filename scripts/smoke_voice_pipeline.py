"""Replay WAVs through the real microphone WebSocket protocol.

Uses a synthetic playback acknowledgment, so this tests backend delivery only.
It neither records the microphone nor measures browser playback quality.
"""

import argparse
import asyncio
import base64
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import websockets  # noqa: E402
from open_llm_vtuber.asr.audio_input import decode_wav  # noqa: E402


async def replay(url: str, paths: list[Path]) -> list[dict]:
    results = []
    async with websockets.connect(url, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "create-new-history"}))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if message.get("type") == "new-history-created":
                break
        for path in paths:
            samples = decode_wav(path.read_bytes())
            start = time.perf_counter()
            for offset in range(0, len(samples), 4096):
                await ws.send(
                    json.dumps(
                        {
                            "type": "mic-audio-data",
                            "audio": samples[offset : offset + 4096].tolist(),
                        }
                    )
                )
            await ws.send(json.dumps({"type": "mic-audio-end"}))
            record = {
                "input": path.name,
                "transcript": "",
                "response": "",
                "audio_segments": 0,
            }
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 90))
                kind = message.get("type")
                if kind == "error":
                    raise RuntimeError(message.get("message"))
                if kind == "user-input-transcription":
                    record["transcript"] = message["text"]
                if kind == "audio":
                    record["response"] += message.get("display_text", {}).get(
                        "text", ""
                    )
                    if message.get("audio"):
                        assert base64.b64decode(message["audio"]).startswith(b"RIFF")
                        record["audio_segments"] += 1
                if kind == "backend-synth-complete":
                    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
                if (
                    kind == "control"
                    and message.get("text") == "conversation-chain-end"
                ):
                    break
            assert (
                record["transcript"] and record["response"] and record["audio_segments"]
            )
            record["seconds"] = round(time.perf_counter() - start, 2)
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path, nargs="+")
    parser.add_argument("--url", default="ws://localhost:12393/client-ws")
    parser.add_argument("--report", type=Path, default=ROOT / "logs/voice_smoke.json")
    args = parser.parse_args()
    records = asyncio.run(replay(args.url, args.wav))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {"mode": "protocol-replay-with-synthetic-playback-ack", "results": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
