"""Crisis support must survive disabled expressions, slow TTS and UI acknowledgement."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx

from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from open_llm_vtuber.agent.output_types import Actions, DisplayText, SentenceOutput
from open_llm_vtuber.config_manager import TTSPreprocessorConfig
from open_llm_vtuber.conversations.conversation_utils import process_agent_output
from open_llm_vtuber.mental_health.companion_store import CompanionStore
from open_llm_vtuber.mental_health.crisis_resources import crisis_resources_payload
from open_llm_vtuber.mental_health.memory_service import JsonlPsychologicalMemoryService
from open_llm_vtuber.mental_health.product_routes import init_product_routes
from open_llm_vtuber.mental_health.safety_guard import RuleBasedSafetyGuard
from open_llm_vtuber.mental_health.schemas import PsychologicalState
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from open_llm_vtuber.mental_health.state_estimator import KeywordStateEstimator
from test_mental_health_agent import (
    FakeDecisionClient,
    FakeDialogueClient,
    FakeLive2DModel,
)


class CrisisSupportTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, directory, *, expressions=True):
        return MentalHealthAgent(
            dialogue_client=FakeDialogueClient(),
            decision_client=FakeDecisionClient(),
            safety_guard=RuleBasedSafetyGuard(),
            state_estimator=KeywordStateEstimator(),
            memory_service=JsonlPsychologicalMemoryService(
                str(Path(directory) / "states.jsonl")
            ),
            system="Supportive conversation.",
            live2d_model=FakeLive2DModel(),
            tts_preprocessor_config=TTSPreprocessorConfig(
                remove_special_char=True,
                translator_config={
                    "translate_audio": False,
                    "translate_provider": "deeplx",
                },
            ),
            faster_first_response=False,
            segment_method="regex",
            expression_enabled=expressions,
        )

    async def test_first_crisis_sentence_has_resources_even_without_expressions(self):
        for expressions in (True, False):
            with self.subTest(expressions=expressions), TemporaryDirectory() as temp:
                agent = self.agent(temp, expressions=expressions)
                outputs = [
                    output
                    async for output in agent.chat(
                        BatchInput(
                            texts=[
                                TextData(source=TextSource.INPUT, content="我不想活了")
                            ]
                        )
                    )
                ]
                text = "".join(output.display_text.text for output in outputs)
                for number in ("12356", "120", "110"):
                    self.assertIn(number, text)
                actions = outputs[0].actions.to_dict()
                self.assertEqual(
                    actions["crisis_resources"], crisis_resources_payload()
                )
                self.assertEqual(actions["strategy"]["primary"], "crisis_support")
                self.assertTrue(actions["crisis_id"])
                self.assertTrue(
                    all(o.actions.crisis_resources is None for o in outputs[1:])
                )
                self.assertEqual(agent._llm.calls, 0)
                self.assertEqual(agent._decision_client.calls, 0)
                if not expressions:
                    self.assertNotIn("expressions", actions)
                    self.assertNotIn("voice_speed", actions)

    async def test_ordinary_turn_has_no_crisis_metadata(self):
        with TemporaryDirectory() as temp:
            agent = self.agent(temp)
            outputs = [
                output
                async for output in agent.chat(
                    BatchInput(
                        texts=[TextData(source=TextSource.INPUT, content="你好")]
                    )
                )
            ]
        for output in outputs:
            self.assertNotIn("crisis_resources", output.actions.to_dict())
            self.assertNotIn("crisis_id", output.actions.to_dict())

    async def test_blocked_response_has_contacts_and_english_stays_local(self):
        guard = RuleBasedSafetyGuard()
        blocked = await guard.check_output("你应该伤害自己")
        self.assertEqual(blocked.action, "block")
        self.assertIn("12356", blocked.safe_response)
        self.assertIn("120", blocked.safe_response)
        english = await guard.check_input("I want to kill myself")
        self.assertIn("local emergency services", english.safe_response)
        self.assertNotIn("12356", english.safe_response)

    def test_payload_is_serializable_and_mutations_cannot_change_resources(self):
        payload = crisis_resources_payload()
        actions = Actions(crisis_resources=payload, crisis_id="test")
        self.assertEqual(
            json.loads(json.dumps(actions.to_dict()))["crisis_resources"], payload
        )
        payload[0]["number"] = "changed"
        self.assertEqual(crisis_resources_payload()[0]["number"], "12356")
        self.assertEqual(Actions().to_dict(), {})

    async def test_safety_notification_precedes_translation_and_tts(self):
        sent = []

        async def send(raw):
            sent.append(json.loads(raw))

        def translate(text):
            self.assertEqual(sent[0]["type"], "crisis-support")
            return text

        async def speak(**kwargs):
            self.assertEqual(sent[0]["actions"]["crisis_id"], "crisis-1")
            self.assertEqual(sent[0]["actions"], kwargs["actions"].to_dict())
            # Simulates an unavailable voice service; the card has already arrived.
            raise RuntimeError("TTS unavailable")

        await process_agent_output(
            SentenceOutput(
                DisplayText("请先联系信任的人。"),
                "请先联系信任的人。",
                Actions(
                    strategy={"primary": "crisis_support"},
                    crisis_resources=crisis_resources_payload(),
                    crisis_id="crisis-1",
                ),
            ),
            SimpleNamespace(character_name="心迹", avatar=None),
            None,
            None,
            send,
            SimpleNamespace(speak=speak),
            SimpleNamespace(translate=translate),
        )
        self.assertEqual([p["type"] for p in sent], ["crisis-support", "error"])

    async def test_normal_delivery_does_not_send_safety_notification(self):
        send = AsyncMock()
        speak = AsyncMock()
        await process_agent_output(
            SentenceOutput(DisplayText("你好。"), "你好。", Actions()),
            SimpleNamespace(character_name="心迹", avatar=None),
            None,
            None,
            send,
            SimpleNamespace(speak=speak),
        )
        send.assert_not_awaited()
        speak.assert_awaited_once()

    async def test_ack_event_is_profile_scoped_and_does_not_downgrade_risk(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "states.db")
            memory = SqlitePsychologicalMemoryService(path, "current")
            store = CompanionStore(memory)
            other = CompanionStore(SqlitePsychologicalMemoryService(path, "other"))
            await memory.append("session", PsychologicalState(risk_level="critical"))
            context = SimpleNamespace(
                agent_engine=SimpleNamespace(_psychological_memory=memory),
                system_config=SimpleNamespace(trial_mode=False),
            )
            app = FastAPI()
            app.include_router(init_product_routes(context))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/companion/events", json={"name": "crisis_ack"}
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(
                    [e["name"] for e in store.list("event")], ["crisis_ack"]
                )
                self.assertEqual(other.list("event"), [])
                self.assertEqual(
                    (await memory.retrieve_recent("session"))[0].risk_level, "critical"
                )
                rejected = await client.post(
                    "/api/companion/events",
                    json={"name": "crisis_ack", "raw_text": "must not be stored"},
                )
                self.assertEqual(rejected.status_code, 422)
                context.system_config.trial_mode = True
                denied = await client.post(
                    "/api/companion/events", json={"name": "crisis_ack"}
                )
                self.assertEqual(denied.status_code, 403)
