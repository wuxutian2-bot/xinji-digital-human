import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from open_llm_vtuber.agent.output_types import Actions
from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from open_llm_vtuber.tts.edge_tts import TTSEngine
from open_llm_vtuber.tts.tts_interface import TTSInterface
from open_llm_vtuber.tts.voice_controls import resolve_voice_controls


class LegacyEngine(TTSInterface):
    def generate_audio(self, text, file_name_no_ext=None):
        return text


class ExpressionTests(unittest.IsolatedAsyncioTestCase):
    def test_unsupported_and_invalid_voice_controls_fall_back(self):
        for speed in (float("nan"), float("inf"), True, "fast", -1, 10):
            resolved = resolve_voice_controls(TTSEngine(), Actions(voice_speed=speed))
            self.assertEqual(resolved["speed"], 1.0)
            self.assertEqual(resolved["fallback"], ["speed"])
        self.assertEqual(
            resolve_voice_controls(
                LegacyEngine(),
                Actions(
                    voice_speed=0.8,
                    voice_style="warm",
                    voice_energy=0.8,
                ),
            ),
            {"speed": 1.0, "fallback": ["speed", "style", "energy"]},
        )

    async def test_concurrent_edge_calls_keep_per_sentence_rate(self):
        engine = TTSEngine()
        with patch("open_llm_vtuber.tts.edge_tts.edge_tts.Communicate") as communicate:
            communicate.return_value.save = AsyncMock()
            await asyncio.gather(
                engine.async_generate_audio_with_options("slow", "slow", speed=0.8),
                engine.async_generate_audio_with_options("fast", "fast", speed=1.2),
            )
        self.assertEqual(
            [call.kwargs["rate"] for call in communicate.call_args_list],
            ["-20%", "+20%"],
        )
        self.assertFalse(hasattr(engine, "rate"))

    async def test_cancelled_edge_call_removes_partial_file(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "partial.mp3"

            async def partial(_):
                path.write_bytes(b"partial")
                raise asyncio.CancelledError()

            engine = TTSEngine()
            with (
                patch.object(
                    engine, "generate_cache_file_name", return_value=str(path)
                ),
                patch(
                    "open_llm_vtuber.tts.edge_tts.edge_tts.Communicate"
                ) as communicate,
            ):
                communicate.return_value.save = partial
                with self.assertRaises(asyncio.CancelledError):
                    await engine.async_generate_audio_with_options("hello")
            self.assertFalse(path.exists())

    async def test_manager_passes_speed_and_legacy_engine_remains_compatible(self):
        engine = TTSEngine()
        with patch.object(
            engine, "async_generate_audio_with_options", new_callable=AsyncMock
        ) as generate:
            await TTSTaskManager()._generate_audio(engine, "text", 0.8)
            self.assertEqual(generate.call_args.kwargs["speed"], 0.8)
        self.assertEqual(
            await TTSTaskManager()._generate_audio(LegacyEngine(), "text", 0.8), "text"
        )
