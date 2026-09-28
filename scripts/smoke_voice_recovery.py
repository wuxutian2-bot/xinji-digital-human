"""Check live backend silence rejection, interruption, and next-turn recovery.

Only synthetic text/audio is sent. Playback completion is simulated.
"""

import asyncio
import json
from pathlib import Path

import websockets


async def receive_end(ws):
    kinds = []
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 60))
        kinds.append(message["type"])
        if message["type"] == "backend-synth-complete":
            await ws.send(json.dumps({"type": "frontend-playback-complete"}))
        if (
            message["type"] == "control"
            and message.get("text") == "conversation-chain-end"
        ):
            return kinds


async def main():
    checks = []
    async with websockets.connect(
        "ws://localhost:12393/client-ws", max_size=16000000
    ) as ws:
        await ws.send(json.dumps({"type": "create-new-history"}))
        while (
            json.loads(await asyncio.wait_for(ws.recv(), 15))["type"]
            != "new-history-created"
        ):
            pass
        await ws.send(json.dumps({"type": "mic-audio-data", "audio": [0.0] * 1600}))
        await ws.send(json.dumps({"type": "mic-audio-end"}))
        kinds = await receive_end(ws)
        assert "error" in kinds and "audio" not in kinds
        checks.append("silence_rejected_and_turn_ended")
        print(checks[-1], flush=True)

        await ws.send(
            json.dumps({"type": "text-input", "text": "请用一句话回应：今天工作很累。"})
        )
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 60))
            assert message["type"] != "error", message
            if message["type"] == "audio":
                break
        await ws.send(
            json.dumps(
                {"type": "interrupt-signal", "text": message["display_text"]["text"]}
            )
        )
        await ws.send(json.dumps({"type": "heartbeat"}))
        while (
            json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] != "heartbeat-ack"
        ):
            pass
        # Flush pre-interrupt in-flight packets up to the server's heartbeat barrier.
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), 1))
            assert message["type"] != "audio", "Old audio after interruption barrier"
        except asyncio.TimeoutError:
            pass
        checks.append("no_old_audio_after_interrupt_barrier")
        print(checks[-1], flush=True)

        await ws.send(
            json.dumps({"type": "text-input", "text": "你好，只回复一句问候。"})
        )
        kinds = await receive_end(ws)
        assert "error" not in kinds and "audio" in kinds, kinds
        checks.append("next_turn_completed_with_audio")
        print(checks[-1], flush=True)
    report = Path(__file__).resolve().parents[1] / "logs/voice_recovery.json"
    report.write_text(
        json.dumps({"mode": "protocol-test", "passed": checks}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
