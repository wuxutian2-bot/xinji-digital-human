"""Product behavior: user control, provenance, isolation and honest execution facts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import json

import httpx
from fastapi import FastAPI

from open_llm_vtuber.mental_health.companion_store import CompanionStore
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from open_llm_vtuber.mental_health.product_routes import init_product_routes
from open_llm_vtuber.mental_health.schemas import PsychologicalState
from open_llm_vtuber.mental_health.support_controls import resolve_support_intent
from open_llm_vtuber.mental_health.intent_estimator import IntentEstimator
from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from open_llm_vtuber.mental_health.decision_client import RuleBasedDecisionClient
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard
from test_mental_health_agent import FakeDialogueClient, FakeLive2DModel
from open_llm_vtuber.config_manager.tts_preprocessor import TTSPreprocessorConfig


class CompanionProductTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "states.db"
        self.memory = SqlitePsychologicalMemoryService(
            str(self.path), "p01", trend_settings={"version": "daily_v2"}
        )
        self.store = CompanionStore(self.memory)
        self.context = SimpleNamespace(
            agent_engine=SimpleNamespace(_psychological_memory=self.memory),
            system_config=SimpleNamespace(
                trial_label="P01", trial_mode=True, synthetic_demo=False
            ),
        )
        app = FastAPI()
        app.include_router(init_product_routes(self.context))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test/api/companion"
        )
        await self.client.put("/consent", json={"accepted": True})

    async def asyncTearDown(self):
        await self.client.aclose()
        self.temp.cleanup()

    async def test_zero_missing_and_partial_correction(self):
        response = await self.client.post(
            "/states",
            json={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "emotion": {"stress": 0, "anxiety": 0.8},
            },
        )
        self.assertEqual(response.status_code, 201)
        record_id = response.json()["id"]
        self.assertEqual(
            (
                await self.client.patch(
                    f"/states/{record_id}", json={"emotion": {"anxiety": 0.2}}
                )
            ).status_code,
            200,
        )
        state = (await self.client.get("/states")).json()[0]["state"]
        self.assertEqual(state["emotion"]["stress"], 0)
        self.assertNotIn("low_mood", state["observed_dimensions"])
        self.assertEqual(
            state["dimension_sources"],
            {"stress": "user_report", "anxiety": "user_correction"},
        )
        trend = (await self.client.get("/trend")).json()["trend"]
        self.assertEqual(
            trend["sources"]["user_report"]["dimensions"]["stress"]["mean"], 0
        )
        self.assertIsNone(
            trend["sources"]["user_report"]["dimensions"]["low_mood"]["mean"]
        )

    async def test_validation_and_consent(self):
        for values in [{}, {"stress": 1.1}, {"unknown": 0.2}]:
            r = await self.client.post(
                "/states",
                json={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "emotion": values,
                },
            )
            self.assertEqual(r.status_code, 422)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        r = await self.client.post(
            "/states", json={"timestamp": future.isoformat(), "emotion": {"stress": 0}}
        )
        self.assertEqual(r.status_code, 422)
        await self.client.put("/consent", json={"accepted": False})
        r = await self.client.post(
            "/states",
            json={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "emotion": {"stress": 0},
            },
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(
            (
                await self.client.post(
                    "/events", json={"name": "visit", "raw_text": "private"}
                )
            ).status_code,
            422,
        )

    async def test_delete_recomputes_and_invalidates_trace(self):
        record_id = await self.memory.append(
            "s",
            PsychologicalState(
                estimator_source="context_v2",
                observed_dimensions=["stress"],
                emotion={"stress": 0.7},
            ),
        )
        self.store.put(
            "turn",
            "t1",
            {"id": "t1", "record_id": record_id, "history_context": {"secret": "old"}},
        )
        self.store.put("turn", "t2", {"id": "t2", "history_context": {"secret": "old"}})
        self.assertEqual(
            (await self.client.delete(f"/states/{record_id}")).status_code, 200
        )
        self.assertIsNone(self.store.get("turn", "t1"))
        self.assertIsNone(self.store.get("turn", "t2")["history_context"])
        self.assertEqual(
            (await self.client.get("/trend")).json()["trend"]["sample_count"], 0
        )

    async def test_actions_persist_only_one_and_require_help_request(self):
        self.store.put("turn", "listen", {"final_strategy": "supportive_listening"})
        self.store.put(
            "turn", "solve", {"final_strategy": "collaborative_problem_solving"}
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/actions", json={"text": "复习一节", "turn_id": "listen"}
                )
            ).status_code,
            409,
        )
        r = await self.client.post(
            "/actions", json={"text": "复习一节", "turn_id": "solve"}
        )
        self.assertEqual(r.status_code, 201)
        action_id = r.json()["id"]
        self.assertEqual(
            (
                await self.client.post(
                    "/actions", json={"text": "另一项", "turn_id": "solve"}
                )
            ).status_code,
            409,
        )
        self.assertEqual(
            CompanionStore(self.memory).get("action", action_id)["text"], "复习一节"
        )
        self.assertEqual(
            (
                await self.client.patch(
                    f"/actions/{action_id}",
                    json={"status": "completed", "feedback": "helpful"},
                )
            ).status_code,
            200,
        )
        self.assertEqual(len(self.memory.list_records()), 0)

    async def test_user_isolation_and_unknown_ids(self):
        other = CompanionStore(SqlitePsychologicalMemoryService(str(self.path), "p02"))
        other.put(
            "turn",
            "private",
            {"id": "private", "final_strategy": "collaborative_problem_solving"},
        )
        other.create_action("仅P02可见", "private")
        self.assertEqual((await self.client.get("/actions")).json(), [])
        self.assertEqual(
            (
                await self.client.put(
                    "/turns/private/feedback", json={"value": "helpful"}
                )
            ).status_code,
            404,
        )
        self.assertEqual((await self.client.get("/turns")).json(), [])

    async def test_audio_receipts_do_not_claim_silent_or_sent_audio_completed(self):
        self.store.put(
            "turn",
            "t",
            {
                "id": "t",
                "scope": "a",
                "sent_segments": [
                    {"id": 0, "has_audio": True},
                    {"id": 1, "has_audio": False},
                ],
            },
        )
        self.assertEqual(self.store.turns()[0]["playback"], "unconfirmed")
        with self.assertRaises(ValueError):
            self.store.record_playback("t", 1, "completed", "a")
        with self.assertRaises(ValueError):
            self.store.record_playback("t", 0, "completed", "other")
        self.store.record_playback("t", 0, "failed", "a")
        self.assertEqual(self.store.turns()[0]["playback"], "failed")

    def agent(self):
        return MentalHealthAgent(
            dialogue_client=FakeDialogueClient(),
            decision_client=RuleBasedDecisionClient(),
            safety_guard=ContextSafetyGuard(),
            state_estimator=ContextStateEstimator(),
            memory_service=self.memory,
            system="Provide supportive conversation.",
            live2d_model=FakeLive2DModel(),
            tts_preprocessor_config=TTSPreprocessorConfig(
                remove_special_char=True,
                translator_config={
                    "translate_audio": False,
                    "translate_provider": "deeplx",
                },
            ),
        )

    async def say(self, agent, text, turn):
        data = BatchInput(
            texts=[TextData(source=TextSource.INPUT, content=text)],
            metadata={"companion_turn_id": turn},
        )
        return [output async for output in agent.chat(data)]

    async def test_feedback_changes_next_turn_and_can_be_cancelled(self):
        agent = self.agent()
        agent.set_support_mode("solve")
        await self.say(agent, "复习安排有点乱", "a")
        self.assertEqual(
            self.store.get("turn", "a")["final_strategy"],
            "collaborative_problem_solving",
        )
        await self.client.put("/turns/a/feedback", json={"value": "unhelpful"})
        await self.say(agent, "我再说一点", "b")
        self.assertEqual(
            self.store.get("turn", "b")["final_strategy"], "reflect_and_clarify"
        )
        await self.client.put("/turns/b/feedback", json={"value": "unhelpful"})
        await self.client.put("/turns/b/feedback", json={"value": "unspecified"})
        await self.say(agent, "再聊聊", "c")
        self.assertEqual(
            self.store.get("turn", "c")["final_strategy"],
            "collaborative_problem_solving",
        )

    async def test_natural_preference_and_safety_override_buttons(self):
        agent = self.agent()
        agent.set_support_mode("solve")
        await self.say(agent, "先别给建议", "a")
        self.assertEqual(agent.support_mode, "listen")
        self.assertEqual(
            self.store.get("turn", "a")["final_strategy"], "supportive_listening"
        )
        await self.say(agent, "现在可以给我建议了", "b")
        self.assertEqual(agent.support_mode, "solve")
        agent.set_support_mode("listen")
        await self.say(agent, "我现在要自杀", "c")
        self.assertEqual(self.store.get("turn", "c")["trace"]["source"], "safety_gate")

    def test_explicit_mode_clear_and_latest_text(self):
        estimator = IntentEstimator()
        intent, mode = resolve_support_intent(
            estimator.estimate("帮我梳理一下"), "solve"
        )
        self.assertEqual(mode, "clarify")
        self.assertEqual(intent.primary, "seeking_clarification")
        agent = self.agent()
        agent.set_support_mode("listen")
        agent.set_support_mode(None)
        self.assertIsNone(agent.support_mode)
        self.assertIsNone(agent._interaction_session["intent"])

    async def test_model_failure_is_visible_without_retained_text(self):
        from open_llm_vtuber.conversations.single_conversation import (
            process_single_conversation,
        )

        agent = self.agent()

        async def fail(*args, **kwargs):
            raise ConnectionError("private diagnostic must not reach UI")
            yield ""

        agent._llm.chat_completion = fail
        self.context.agent_engine = agent
        self.context.history_uid = "current"
        self.context.asr_engine = None
        self.context.character_config = SimpleNamespace(
            human_name="test", conf_uid="isolated"
        )
        self.context.live2d_model = FakeLive2DModel()
        self.context.tts_engine = None
        self.context.translate_engine = None
        send = AsyncMock()
        with patch(
            "open_llm_vtuber.conversations.single_conversation.store_message"
        ) as stored:
            await process_single_conversation(self.context, send, "c", "测试输入")
            stored.assert_not_called()
        turn = self.store.turns()[0]
        self.assertEqual(turn["generation"], "failed")
        self.assertEqual(turn["trace"]["source"], "rules")
        self.assertEqual(turn["sent_segments"], [])
        errors = [json.loads(call.args[0]) for call in send.await_args_list]
        self.assertTrue(any(e.get("type") == "error" for e in errors))
        self.assertNotIn("private diagnostic", json.dumps(errors))

    async def test_interrupt_does_not_bypass_no_transcript_consent(self):
        from open_llm_vtuber.conversations.conversation_handler import (
            handle_individual_interrupt,
        )

        self.context.agent_engine = self.agent()
        self.context.history_uid = "current"
        with patch(
            "open_llm_vtuber.conversations.conversation_handler.store_message"
        ) as stored:
            await handle_individual_interrupt(
                "c", {"c": None}, self.context, "private heard text"
            )
            stored.assert_not_called()

    async def test_tts_empty_result_is_failure_but_keeps_display_text(self):
        from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
        from open_llm_vtuber.agent.output_types import DisplayText, Actions

        manager = TTSTaskManager()
        engine = SimpleNamespace(
            supported_controls=frozenset(),
            async_generate_audio_with_options=AsyncMock(return_value=None),
        )
        await manager._process_tts(
            "你好", DisplayText("你好"), Actions(), None, engine, 0
        )
        payload, _ = await manager._payload_queue.get()
        self.assertTrue(payload["tts_error"])
        self.assertEqual(payload["display_text"]["text"], "你好")
        self.assertFalse(payload["audio"])

    def test_trial_profile_creation_isolated_and_safe(self):
        import importlib.util
        from open_llm_vtuber.config_manager import read_yaml, validate_config

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "create_trial_profile", root / "scripts/create_trial_profile.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = [
            module.create_profile(
                root / "config_templates/conf.ZH.default.yaml",
                Path(self.temp.name) / label,
                label,
            )
            for label in ("P01", "P02")
        ]
        configs = [validate_config(read_yaml(str(p))) for p in paths]
        first, second = [
            c.character_config.agent_config.agent_settings.mental_health_agent.memory
            for c in configs
        ]
        self.assertNotEqual(first.user_id, second.user_id)
        self.assertNotEqual(first.sqlite_path, second.sqlite_path)
        bad = read_yaml(str(paths[0]))
        bad["system_config"]["host"] = "0.0.0.0"
        from open_llm_vtuber.config_manager.main import Config

        with self.assertRaises(ValueError):
            Config(**bad)


if __name__ == "__main__":
    unittest.main()
