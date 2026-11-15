import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs
import wave

import httpx
from fastapi import FastAPI
from pydantic import ValidationError

from open_llm_vtuber.agent.output_types import Actions
from open_llm_vtuber.config_manager.tts import TTSConfig
from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from open_llm_vtuber.mental_health.companion_store import CompanionStore
from open_llm_vtuber.mental_health.product_routes import init_product_routes
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from open_llm_vtuber.tts.breeze_tts import (
    PREVIEW_TEXT,
    TTSEngine,
    build_instruction,
    pcm_to_wav,
)
from open_llm_vtuber.tts.voice_controls import resolve_voice_controls


PCM = b"\x01\x00" * 24000


def handler(request):
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(200, content=PCM)


class BreezeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.engine = TTSEngine("gentle", transport=httpx.MockTransport(handler))
        self.path = str(Path(self.folder.name) / "audio.wav")
        self.cache = patch.object(
            self.engine, "generate_cache_file_name", return_value=self.path
        )
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def test_instruction_combinations(self):
        self.assertEqual(
            build_instruction("朋友。", "warm", 0.85, 0.8),
            "朋友。语气温暖、带着关切，语速稍慢，声音轻一些。",
        )
        self.assertEqual(build_instruction("", "calm", 1, 1), "语气平静、柔和。")
        self.assertEqual(
            build_instruction("", "steady", 1.2, 1.2),
            "语气沉稳、清晰、让人安心，语速稍快，更有活力。",
        )
        self.assertEqual(
            build_instruction("base", "unknown", 1, None, {"unknown": "ignore"}),
            "base。",
        )
        self.assertEqual(build_instruction("", None, 0.95, 1.1), "")
        self.assertEqual(
            build_instruction("", "warm", 1.05, 0.9, {"warm": "关切"}), "关切。"
        )

    async def test_pcm_creates_valid_wav_and_per_utterance_form(self):
        captured = []

        def capture(request):
            captured.append(parse_qs(request.content.decode()))
            return handler(request)

        self.engine._transport = httpx.MockTransport(capture)
        path = await self.engine.async_generate_audio_with_options(
            "测试",
            speed=0.85,
            style="warm",
            energy=0.8,
            voice_id="custom",
            instruction="用户描述",
        )
        with wave.open(path) as audio:
            self.assertEqual(
                (
                    audio.getframerate(),
                    audio.getnchannels(),
                    audio.getsampwidth(),
                    audio.getnframes(),
                ),
                (24000, 1, 2, 24000),
            )
        self.assertEqual(captured[0]["voice_id"], ["custom"])
        self.assertIn("用户描述。语气温暖", captured[0]["instruction"][0])
        self.assertEqual(captured[0]["seed"], ["42"])
        self.assertNotIn("response_format", captured[0])
        self.assertEqual(self.engine.voice_id, "gentle")

    def test_synchronous_path(self):
        path = self.engine.generate_audio("测试")
        self.assertTrue(Path(path).read_bytes().startswith(b"RIFF"))

    async def test_busy_retries_and_exhaustion(self):
        calls = 0

        def busy(request):
            nonlocal calls
            calls += 1
            return httpx.Response(409) if calls <= 2 else handler(request)

        self.engine._transport = httpx.MockTransport(busy)
        with patch(
            "open_llm_vtuber.tts.breeze_tts.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            self.assertIsNotNone(await self.engine.async_generate_audio("测试"))
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.2, 0.4])
        self.engine._transport = httpx.MockTransport(lambda r: httpx.Response(409))
        with patch(
            "open_llm_vtuber.tts.breeze_tts.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            self.assertIsNone(await self.engine.async_generate_audio("测试"))
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.2, 0.4, 0.8])

    async def test_empty_odd_and_broken_responses_fail(self):
        for body in (b"", b"x"):
            self.engine._transport = httpx.MockTransport(
                lambda r: httpx.Response(200, content=body)
            )
            self.assertIsNone(await self.engine.async_generate_audio("测试"))

        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"\0\0"
                raise httpx.ReadError("disconnected")

        self.engine._transport = httpx.MockTransport(
            lambda r: httpx.Response(200, stream=BrokenStream())
        )
        self.assertIsNone(await self.engine.async_generate_audio("测试"))
        self.assertFalse(Path(self.path).exists())

    async def test_concurrency_and_cancellation_release_slot(self):
        active, peak = 0, 0

        async def delayed(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.03)
                return handler(request)
            finally:
                active -= 1

        self.engine._transport = httpx.MockTransport(delayed)
        await asyncio.gather(*(self.engine.synthesize_wav(str(i)) for i in range(3)))
        self.assertEqual(peak, 1)
        task = asyncio.create_task(self.engine.synthesize_wav("cancel"))
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(await asyncio.wait_for(self.engine.synthesize_wav("next"), 1))

    def test_controls_validate_and_report_fallback(self):
        requested = Actions(
            voice_style="steady",
            voice_speed=0.85,
            voice_energy=0.8,
            voice_id="custom",
            voice_instruction="温柔",
        )
        result = resolve_voice_controls(self.engine, requested)
        self.assertEqual(
            (
                result["style"],
                result["energy"],
                result["voice_id"],
                result["instruction"],
            ),
            ("steady", 0.8, "custom", "温柔"),
        )
        self.assertEqual(result["fallback"], [])
        for energy in (float("nan"), float("inf"), True, "loud", 0.4, 1.6):
            result = resolve_voice_controls(
                self.engine, Actions(voice_energy=energy, voice_style="unknown")
            )
            self.assertIsNone(result["energy"])
            self.assertEqual(result["fallback"], ["style", "energy"])
        result = resolve_voice_controls(SimpleNamespace(), requested)
        self.assertIsNone(result["style"])
        self.assertEqual(
            result["fallback"], ["speed", "style", "energy", "voice_id", "instruction"]
        )

    async def test_manager_forwards_voice_controls(self):
        with patch.object(
            self.engine, "async_generate_audio_with_options", new_callable=AsyncMock
        ) as generate:
            await TTSTaskManager()._generate_audio(
                self.engine,
                "text",
                0.85,
                style="warm",
                energy=0.8,
                voice_id="custom",
                instruction="用户描述",
            )
            self.assertEqual(generate.call_args.kwargs["voice_id"], "custom")
            self.assertEqual(generate.call_args.kwargs["style"], "warm")

    def test_config_requires_saved_voice_and_selected_section(self):
        for data in (
            {"tts_model": "breeze_tts"},
            {"tts_model": "breeze_tts", "breeze_tts": {"voice_id": "../bad"}},
        ):
            with self.assertRaises(ValidationError):
                TTSConfig.model_validate(data)
        self.assertEqual(
            TTSConfig.model_validate(
                {"tts_model": "breeze_tts", "breeze_tts": {"voice_id": "saved"}}
            ).breeze_tts.seed,
            42,
        )


class VoiceRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.memory = SqlitePsychologicalMemoryService(
            str(Path(self.folder.name) / "states.db"), "p1"
        )
        self.store = CompanionStore(self.memory)
        self.calls = []

        def transport(request):
            self.calls.append(request)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/v1/voices":
                return httpx.Response(200, json={"id": "saved"})
            if request.method == "DELETE":
                return httpx.Response(200, json={"file_kept": True})
            return httpx.Response(200, content=PCM)

        self.engine = TTSEngine(
            "gentle",
            transport=httpx.MockTransport(transport),
            voices_dir=self.folder.name,
            presets={"gentle": {"voice_id": "gentle", "label": "温柔"}},
        )
        self.context = SimpleNamespace(
            tts_engine=self.engine,
            agent_engine=SimpleNamespace(_psychological_memory=self.memory),
            system_config=SimpleNamespace(
                trial_mode=True, synthetic_demo=False, trial_label="P1"
            ),
        )
        app = FastAPI()
        app.include_router(init_product_routes(self.context))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test/api/companion"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def consent(self):
        await self.client.put("/consent", json={"accepted": True})

    async def test_consent_validation_and_unavailable_fallback(self):
        for path, method, body in (
            ("/voice/preview", "POST", {"description": "温柔"}),
            ("/voice", "PUT", {"mode": "default"}),
        ):
            self.assertEqual(
                (await self.client.request(method, path, json=body)).status_code, 403
            )
        await self.consent()
        for body in (
            {},
            {"description": " "},
            {"description": "x" * 201},
            {"description": "模仿某某的声音"},
            {"description": "温柔", "seed": True},
            {"preset_id": "gentle", "description": "温柔"},
            {"description": "温柔", "voice_id": "secret"},
        ):
            self.assertEqual(
                (await self.client.post("/voice/preview", json=body)).status_code, 422
            )
        self.assertEqual(
            (
                await self.client.put(
                    "/voice", json={"mode": "preset", "preset_id": "secret"}
                )
            ).status_code,
            422,
        )
        self.context.tts_engine = None
        self.assertFalse((await self.client.get("/voice")).json()["available"])
        self.assertEqual(
            (await self.client.put("/voice", json={"mode": "default"})).status_code, 200
        )

    async def test_preset_and_default_persist_export_and_events(self):
        await self.consent()
        status = (await self.client.get("/voice")).json()
        self.assertIsNone(status["preference"])
        self.assertEqual(
            status["presets"], [{"id": "gentle", "label": "温柔", "description": ""}]
        )
        r = await self.client.post("/voice/preview", json={"preset_id": "gentle"})
        self.assertEqual(r.headers["content-type"], "audio/wav")
        self.assertEqual(r.content, pcm_to_wav(PCM))
        r = await self.client.put(
            "/voice", json={"mode": "preset", "preset_id": "gentle"}
        )
        self.assertEqual(r.json()["voice_id"], "gentle")
        self.assertEqual(
            (await self.client.get("/export")).json()["voice_preference"]["mode"],
            "preset",
        )
        await self.client.put("/voice", json={"mode": "default"})
        self.assertEqual(
            (await self.client.get("/voice")).json()["preference"]["mode"], "default"
        )
        self.assertIn(
            "voice_preference_updated", [e["name"] for e in self.store.list("event")]
        )

    async def test_custom_registers_exact_preview_and_requires_match(self):
        await self.consent()
        choice = {"mode": "custom", "description": "温柔", "seed": 7}
        self.assertEqual(
            (await self.client.put("/voice", json=choice)).status_code, 409
        )
        await self.client.post(
            "/voice/preview", json={"description": " 温柔 ", "seed": 7}
        )
        response = await self.client.put("/voice", json={**choice, "seed": 8})
        self.assertEqual(response.status_code, 409)
        response = await self.client.put("/voice", json=choice)
        self.assertEqual(response.status_code, 200)
        voice_id = response.json()["voice_id"]
        self.assertTrue(voice_id.startswith("user_"))
        registration = [r for r in self.calls if r.url.path == "/v1/voices"][-1]
        self.assertIn(pcm_to_wav(PCM), registration.content)
        self.assertIn(PREVIEW_TEXT.encode(), registration.content)
        self.assertEqual(
            len([r for r in self.calls if r.url.path == "/v1/audio/speech"]), 1
        )
        # Deletion remains user-bound, including voices replaced by a default.
        (Path(self.folder.name) / f"{voice_id}.breeze").write_bytes(b"saved")
        other = SqlitePsychologicalMemoryService(str(self.memory.storage_path), "other")
        CompanionStore(other).put("voice_preference", "current", {"mode": "default"})
        await self.client.put("/voice", json={"mode": "default"})
        self.assertEqual((await self.client.delete("/profile")).status_code, 200)
        self.assertFalse((Path(self.folder.name) / f"{voice_id}.breeze").exists())
        self.assertIsNone(self.store.get("voice_preference", "current"))
        self.assertIsNotNone(CompanionStore(other).get("voice_preference", "current"))

    async def test_agent_reads_changed_preference_on_next_turn(self):
        from test_companion_product import CompanionProductTests
        from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource

        fixture = CompanionProductTests()
        fixture.memory = self.memory
        agent = fixture.agent()
        self.store.put(
            "voice_preference",
            "current",
            {"mode": "custom", "voice_id": "user_test", "description": "清晰温柔"},
        )
        data = BatchInput(texts=[TextData(source=TextSource.INPUT, content="你好")])
        outputs = [o async for o in agent.chat(data)]
        self.assertTrue(outputs)
        self.assertEqual(outputs[0].actions.voice_id, "user_test")
        self.assertEqual(outputs[0].actions.voice_instruction, "清晰温柔")
        self.store.put("voice_preference", "current", {"mode": "default"})
        outputs = [o async for o in agent.chat(data)]
        self.assertIsNone(outputs[0].actions.voice_id)
        self.assertIsNone(outputs[0].actions.voice_instruction)

    async def test_distress_and_crisis_replies_keep_intended_voice(self):
        from test_companion_product import CompanionProductTests
        from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource

        fixture = CompanionProductTests()
        fixture.memory = self.memory
        for text, style, speed in (
            ("我现在很难过，也很低落。", "warm", 0.9),
            ("我现在想自杀，已经准备伤害自己。", "steady", 0.85),
        ):
            agent = fixture.agent()
            data = BatchInput(texts=[TextData(source=TextSource.INPUT, content=text)])
            outputs = [o async for o in agent.chat(data)]
            self.assertTrue(outputs)
            for output in outputs:
                self.assertEqual(output.actions.voice_style, style)
                self.assertEqual(output.actions.voice_speed, speed)

    async def test_five_attempt_limit_and_profile_isolation(self):
        await self.consent()
        for i in range(5):
            self.assertEqual(
                (
                    await self.client.post(
                        "/voice/preview", json={"description": "温柔", "seed": i}
                    )
                ).status_code,
                200,
            )
        self.assertEqual(
            (
                await self.client.post("/voice/preview", json={"description": "温柔"})
            ).status_code,
            429,
        )
        self.memory.user_id = "p2"
        await self.consent()
        self.assertEqual(
            (
                await self.client.put(
                    "/voice", json={"mode": "custom", "description": "温柔", "seed": 4}
                )
            ).status_code,
            409,
        )
        self.assertEqual(
            (
                await self.client.post("/voice/preview", json={"description": "温柔"})
            ).status_code,
            200,
        )
        self.memory.user_id = "p1"
        await self.client.put("/voice", json={"mode": "default"})
        self.assertEqual(
            (
                await self.client.post("/voice/preview", json={"description": "温柔"})
            ).status_code,
            200,
        )
