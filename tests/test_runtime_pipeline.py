"""Regressions for delivery completion, disabled ASR and session isolation."""

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

from open_llm_vtuber.agent.output_types import Actions, DisplayText
from open_llm_vtuber.config_manager import Config, read_yaml
from open_llm_vtuber.config_manager.asr import ASRConfig
from open_llm_vtuber.conversations.conversation_utils import (
    finalize_conversation_turn,
    process_user_input,
)
from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from open_llm_vtuber.message_handler import message_handler
from open_llm_vtuber.service_context import ServiceContext


class RuntimePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_drains_in_order_before_completion_and_immediate_ack(self):
        manager = TTSTaskManager()
        sent = []
        send_started = asyncio.Event()
        release_send = asyncio.Event()

        async def send(raw):
            payload = json.loads(raw)
            if payload["type"] == "audio":
                send_started.set()
                await release_send.wait()
            sent.append(payload)
            if payload["type"] == "backend-synth-complete":
                message_handler.handle_message(
                    "test-client", {"type": "frontend-playback-complete"}
                )

        manager._sequence_counter = 2
        manager._sender_task = asyncio.create_task(manager._process_payload_queue(send))
        await manager._payload_queue.put(({"type": "audio", "order": 1}, 1))
        await manager._payload_queue.put(({"type": "audio", "order": 0}, 0))
        finish = asyncio.create_task(
            finalize_conversation_turn(manager, send, "test-client")
        )
        try:
            await asyncio.wait_for(send_started.wait(), 1)
            self.assertFalse(finish.done())
            self.assertEqual(sent, [])
            release_send.set()
            await asyncio.wait_for(finish, 1)
            self.assertEqual([p["order"] for p in sent if p["type"] == "audio"], [0, 1])
            self.assertEqual(
                [p["type"] for p in sent],
                [
                    "audio",
                    "audio",
                    "backend-synth-complete",
                    "force-new-message",
                    "control",
                ],
            )
            self.assertEqual(sent[-1]["text"], "conversation-chain-end")
        finally:
            finish.cancel()
            manager.clear()
            message_handler.cleanup_client("test-client")

    async def test_send_failure_does_not_hang_completion(self):
        manager = TTSTaskManager()

        async def failed_send(raw):
            raise ConnectionError("disconnected")

        try:
            await manager.speak(
                "", DisplayText("silent"), Actions(), None, None, failed_send
            )
            with self.assertRaises(ConnectionError):
                await asyncio.wait_for(manager.wait_for_completion(), 1)
        finally:
            manager.clear()

    async def test_disabled_asr_skips_initialization_and_rejects_audio(self):
        context = ServiceContext()
        context.character_config = SimpleNamespace(asr_config=None)
        with patch(
            "open_llm_vtuber.service_context.ASRFactory.get_asr_system"
        ) as factory:
            context.init_asr(ASRConfig(enabled=False, asr_model="sherpa_onnx_asr"))
        factory.assert_not_called()
        self.assertIsNone(context.asr_engine)
        with self.assertRaisesRegex(ValueError, "Speech input is disabled"):
            await process_user_input(np.zeros(160, dtype=np.float32), None, AsyncMock())
        self.assertEqual(await process_user_input("hello", None, AsyncMock()), "hello")

    async def test_cached_engines_get_distinct_mental_health_agents(self):
        path = (
            Path(__file__).resolve().parents[1] / "config_templates/conf.default.yaml"
        )
        data = read_yaml(str(path))
        data["character_config"]["agent_config"]["conversation_agent_choice"] = (
            "mental_health_agent"
        )
        config = Config.model_validate(data)
        cached_agent = object()
        engine = object()
        sessions = []
        for _ in range(2):
            context = ServiceContext()
            await context.load_cache(
                config=config.model_copy(deep=True),
                system_config=config.system_config.model_copy(deep=True),
                character_config=config.character_config.model_copy(deep=True),
                live2d_model=SimpleNamespace(emo_map={"neutral": 0}),
                asr_engine=None,
                tts_engine=engine,
                vad_engine=None,
                agent_engine=cached_agent,
                translate_engine=None,
            )
            sessions.append(context)
        first, second = sessions
        self.assertIs(first.tts_engine, second.tts_engine)
        self.assertIsNot(first.agent_engine, second.agent_engine)
        self.assertIsNot(first.agent_engine, cached_agent)
        self.assertNotEqual(
            first.agent_engine._psychological_memory_scope,
            second.agent_engine._psychological_memory_scope,
        )
        first.agent_engine._memory.append({"role": "user", "content": "private"})
        self.assertEqual(second.agent_engine._memory, [])
