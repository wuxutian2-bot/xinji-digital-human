import asyncio
from io import BytesIO
import json
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import wave

import numpy as np
from fastapi import FastAPI
import httpx

from open_llm_vtuber.asr.audio_input import decode_wav, validate_audio
from open_llm_vtuber.conversations.conversation_utils import process_user_input
from open_llm_vtuber.conversations.conversation_handler import (
    handle_individual_interrupt,
)
from open_llm_vtuber.websocket_handler import WebSocketHandler
from open_llm_vtuber.routes import init_webtool_routes


def wav_bytes(rate=16000, channels=1):
    buffer = BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        samples = np.full((rate // 10, channels), 8192, dtype="<i2")
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


class AudioInputTests(unittest.IsolatedAsyncioTestCase):
    def test_wav_metadata_and_resampling(self):
        raw = wav_bytes(48000, 2)
        # Real RIFF files can contain chunks before fmt/data: never assume 44 bytes.
        extra = b"JUNK" + struct.pack("<I", 4) + b"test"
        raw = (
            raw[:4]
            + struct.pack("<I", len(raw) - 8 + len(extra))
            + raw[8:12]
            + extra
            + raw[12:]
        )
        audio = decode_wav(raw)
        self.assertEqual(audio.shape, (1600,))
        self.assertEqual(audio.dtype, np.float32)
        self.assertAlmostEqual(float(audio[100]), 0.25, places=3)

    def test_invalid_audio_rejected(self):
        for samples in [[], [float("nan")], [float("inf")], [32767], [[0.1]], [0.0]]:
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                validate_audio(samples)
        for data in [b"not a wav", wav_bytes()[:-10]]:
            with self.assertRaises(ValueError):
                decode_wav(data)
        with self.assertRaisesRegex(ValueError, "too long"):
            validate_audio(np.ones(16000 * 60 + 1, dtype=np.float32))

    async def test_silence_and_empty_transcript_never_reach_dialogue(self):
        asr = SimpleNamespace(
            SAMPLE_RATE=16000, async_transcribe_np=AsyncMock(return_value="  ")
        )
        with self.assertRaisesRegex(ValueError, "No speech audio"):
            await process_user_input(np.zeros(100), asr, AsyncMock())
        asr.async_transcribe_np.assert_not_called()
        with self.assertRaisesRegex(ValueError, "No speech recognized"):
            await process_user_input(np.full(100, 0.1), asr, AsyncMock())

    async def test_raw_vad_pcm_is_normalized(self):
        handler = WebSocketHandler(None)
        handler.client_contexts["test"] = SimpleNamespace(
            asr_engine=object(),
            vad_engine=SimpleNamespace(
                detect_speech=lambda chunk: [
                    np.full(1024, 16384, dtype="<i2").tobytes()
                ]
            ),
        )
        handler.received_data_buffers["test"] = np.array([], dtype=np.float32)
        socket = SimpleNamespace(send_text=AsyncMock())
        await handler._handle_raw_audio_data(socket, "test", {"audio": [0.5] * 1024})
        np.testing.assert_allclose(handler.received_data_buffers["test"], 0.5)
        self.assertEqual(
            json.loads(socket.send_text.call_args.args[0])["text"], "mic-audio-end"
        )

    async def test_audio_buffer_limit_and_invalid_chunk_reset(self):
        handler = WebSocketHandler(None)
        handler.client_contexts["test"] = SimpleNamespace(asr_engine=object())
        handler.received_data_buffers["test"] = np.ones(16000 * 60, dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            await handler._handle_audio_data(None, "test", {"audio": [0.1]})
        self.assertEqual(handler.received_data_buffers["test"].size, 0)
        handler.received_data_buffers["test"] = np.ones(20, dtype=np.float32)
        with self.assertRaises(ValueError):
            await handler._handle_audio_data(None, "test", {"audio": [float("nan")]})
        self.assertEqual(handler.received_data_buffers["test"].size, 0)

    async def test_interrupt_waits_for_old_turn_cleanup(self):
        cleaned = []

        async def turn():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)

        task = asyncio.create_task(turn())
        await asyncio.sleep(0)
        agent = SimpleNamespace(
            handle_interrupt=lambda text: self.assertEqual(cleaned, [True])
        )
        await handle_individual_interrupt(
            "test",
            {"test": task},
            SimpleNamespace(agent_engine=agent, history_uid=None),
            "heard",
        )
        self.assertTrue(task.done())

    async def test_sensevoice_missing_path_is_actionable(self):
        from open_llm_vtuber.asr.sherpa_onnx_asr import VoiceRecognition

        with self.assertRaisesRegex(FileNotFoundError, "prepare_sensevoice"):
            VoiceRecognition(model_type="sense_voice", sense_voice=None)

    async def test_upload_route_and_text_recovery(self):
        asr = SimpleNamespace(
            SAMPLE_RATE=16000, async_transcribe_np=AsyncMock(return_value=" 测试 ")
        )
        context = SimpleNamespace(asr_engine=asr)
        app = FastAPI()
        app.include_router(init_webtool_routes(context))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/asr", files={"file": ("test.wav", wav_bytes(48000, 2))}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"text": "测试"})
            response = await client.post(
                "/asr", files={"file": ("bad.wav", b"not wav")}
            )
            self.assertEqual(response.status_code, 400)
            context.asr_engine = None
            response = await client.post(
                "/asr", files={"file": ("test.wav", wav_bytes())}
            )
            self.assertEqual(response.status_code, 503)
        self.assertEqual(await process_user_input("hello", None, AsyncMock()), "hello")
