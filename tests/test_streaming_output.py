import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import unittest

from open_llm_vtuber.agent.agent_factory import AgentFactory
from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from open_llm_vtuber.config_manager import TTSPreprocessorConfig
from open_llm_vtuber.config_manager.agent import MentalHealthAgentConfig
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from test_mental_health_agent import FakeDecisionClient, FakeLive2DModel


class TokenDialogue:
    def __init__(self, tokens, delay=0):
        self.tokens = tokens
        self.delay = delay
        self.consumed = []
        self.closed = False

    async def chat_completion(self, *args):
        try:
            for token in self.tokens:
                if self.delay:
                    await asyncio.sleep(self.delay)
                if isinstance(token, Exception):
                    raise token
                self.consumed.append(token)
                yield token
        finally:
            self.closed = True


class StreamingOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.batch = BatchInput(
            texts=[TextData(source=TextSource.INPUT, content="今天想聊一会。")],
            metadata={"companion_turn_id": "turn"},
        )

    def agent(self, dialogue, streaming=True):
        return MentalHealthAgent(
            dialogue_client=dialogue,
            decision_client=FakeDecisionClient(),
            safety_guard=ContextSafetyGuard(),
            state_estimator=ContextStateEstimator(),
            memory_service=SqlitePsychologicalMemoryService(
                str(Path(self.temp.name) / "memory.db"), f"profile-{streaming}"
            ),
            system="Listen carefully.",
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
            streaming_output=streaming,
        )

    async def test_midstream_block_discards_tail_closes_model_and_saves_spoken_prefix(
        self,
    ):
        dialogue = TokenDialogue(
            [
                "我在听。",
                "你应",
                {"type": "text_delta", "text": "该去死。未发。"},
                "不应读取",
            ]
        )
        agent = self.agent(dialogue)
        stream = agent.chat(self.batch)
        first = await anext(stream)
        self.assertEqual(first.display_text.text, "我在听。")
        self.assertEqual(dialogue.consumed, ["我在听。"])
        second = await anext(stream)
        self.assertTrue(dialogue.closed)
        self.assertEqual(second.actions.strategy["primary"], "supportive_listening")
        outputs = [first, second] + [out async for out in stream]
        actual = "".join(item.display_text.text for item in outputs)
        fixed = (await agent._safety_guard.check_output("你应该去死。")).safe_response
        self.assertEqual(actual, "我在听。" + fixed)
        self.assertEqual(len(dialogue.consumed), 3)
        self.assertEqual(agent._memory[-1]["content"], actual)
        turn = agent.companion.get("turn", "turn")
        self.assertTrue(turn["trace"]["output_safety_override"])
        self.assertIn(
            "output_safety_block_midstream",
            turn["trace"]["coordination"]["reason_codes"],
        )
        self.assertFalse(turn["trace"]["late_output_flag"])
        self.assertNotIn("你应该去死", json.dumps(turn, ensure_ascii=False))

    async def test_50ms_deltas_yield_first_sentence_before_end_and_match_buffered(self):
        tokens = [
            "第一",
            "句。",
            {"type": "text_delta", "text": "第二句！"},
            "第三句？",
        ]
        all_text = []
        for streaming in (True, False):
            dialogue = TokenDialogue(tokens, delay=0.05)
            agent = self.agent(dialogue, streaming=streaming)
            stream = agent.chat(self.batch)
            start = perf_counter()
            first = await anext(stream)
            first_time = perf_counter() - start
            self.assertEqual(first.display_text.text, "第一句。")
            self.assertEqual(dialogue.consumed, tokens[:2] if streaming else tokens)
            self.assertEqual(dialogue.closed, not streaming)
            rest = [o.display_text.text async for o in stream]
            if streaming:
                self.assertGreater(perf_counter() - start - first_time, 0.08)
            all_text.append([first.display_text.text, *rest])
        self.assertEqual(all_text[0], all_text[1])
        self.assertEqual(all_text[0], ["第一句。", "第二句！", "第三句？"])

    async def test_rewrite_and_full_reply_only_flag_are_distinct(self):
        agent = self.agent(TokenDialogue(["你患有焦虑症。", "你应该。", "伤害自己。"]))
        outputs = [o.display_text.text async for o in agent.chat(self.batch)]
        self.assertEqual(len(outputs), 3)
        self.assertIn("无法作出诊断", outputs[0])
        self.assertEqual(outputs[1:], ["你应该。", "伤害自己。"])
        trace = agent.companion.get("turn", "turn")["trace"]
        self.assertTrue(trace["output_safety_override"])
        self.assertTrue(trace["late_output_flag"])
        self.assertNotIn(
            "output_safety_block_midstream", trace["coordination"]["reason_codes"]
        )
        self.assertEqual(agent._memory[-1]["content"], "".join(outputs))

    async def test_buffered_block_suppresses_entire_model_reply(self):
        dialogue = TokenDialogue(["我在听。", "你应该去死。", "之后的文本。"])
        agent = self.agent(dialogue, streaming=False)
        outputs = [o.display_text.text async for o in agent.chat(self.batch)]
        self.assertEqual(len(dialogue.consumed), 3)
        self.assertNotIn("我在听", "".join(outputs))
        self.assertIn("不能提供", "".join(outputs))
        self.assertFalse(
            agent.companion.get("turn", "turn")["trace"]["late_output_flag"]
        )

    async def test_cross_sentence_match_alone_only_marks_the_trace(self):
        tokens = ["你应该。", "伤害自己。"]
        agent = self.agent(TokenDialogue(tokens))
        outputs = [item.display_text.text async for item in agent.chat(self.batch)]
        self.assertEqual(outputs, tokens)
        trace = agent.companion.get("turn", "turn")["trace"]
        self.assertTrue(trace["late_output_flag"])
        self.assertFalse(trace["output_safety_override"])

    async def test_length_cut_newline_trailing_text_and_split_expression(self):
        prefix = "好" * 58
        agent = self.agent(TokenDialogue([prefix + "[j", "oy]可以\n", "末尾"]))
        outputs = [o.display_text.text async for o in agent.chat(self.batch)]
        self.assertEqual(outputs, [prefix, "可以\n", "末尾"])
        self.assertEqual(agent._memory[-1]["content"], "".join(outputs))

    async def test_empty_stream_uses_guard_replacement(self):
        agent = self.agent(TokenDialogue([{"type": "noop"}, "   "]))
        outputs = [o async for o in agent.chat(self.batch)]
        self.assertIn("暂时没能生成", outputs[0].display_text.text)

    async def test_hidden_thoughts_remain_silent_and_blocked_reply_is_audible(self):
        agent = self.agent(
            TokenDialogue(["<think>想一想。", "继续思考。", "你应该去死。"])
        )
        outputs = [o async for o in agent.chat(self.batch)]
        audible = "".join(o.tts_text for o in outputs)
        self.assertNotIn("思考", audible)
        self.assertNotIn("想一想", audible)
        self.assertIn("不能提供", audible)
        self.assertEqual(
            agent._memory[-1]["content"], "".join(o.display_text.text for o in outputs)
        )

    async def test_finishing_generation_preserves_early_receipts_and_feedback(self):
        agent = self.agent(TokenDialogue(["第一句。", "第二句。"]))
        stream = agent.chat(self.batch)
        await anext(stream)
        agent.companion.update_turn(
            "turn",
            sent_segments=[{"id": 0, "has_audio": True, "sent": True}],
            feedback="helpful",
        )
        agent.companion.record_playback(
            "turn", 0, "completed", agent._psychological_memory_scope
        )
        _ = [o async for o in stream]
        turn = agent.companion.turns()[0]
        self.assertEqual(turn["generation"], "completed")
        self.assertEqual(turn["playback"], "completed")
        self.assertEqual(turn["feedback"], "helpful")

    async def test_close_or_failure_keeps_only_emitted_prefix(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                dialogue = TokenDialogue(
                    ["已经发出。", RuntimeError("model disconnected")]
                )
                agent = self.agent(dialogue)
                stream = agent.chat(self.batch)
                await anext(stream)
                if fail:
                    with self.assertRaises(RuntimeError):
                        await anext(stream)
                else:
                    await stream.aclose()
                self.assertTrue(dialogue.closed)
                self.assertEqual(agent._memory[-1]["content"], "已经发出。")
                self.assertIsNone(agent._interaction_session["strategy"])
                self.assertEqual(
                    agent.companion.get("turn", "turn")["generation"],
                    "failed" if fail else "interrupted",
                )

    def test_config_default_and_factory_switch(self):
        dialogue = {
            "base_url": "http://localhost:8000/v1",
            "model": "test",
            "llm_api_key": "local",
        }
        for option in ({}, {"streaming_output": False}):
            settings = MentalHealthAgentConfig(
                dialogue=dialogue, memory={"enabled": False}, **option
            )
            agent = AgentFactory.create_agent(
                "mental_health_agent",
                {"mental_health_agent": settings.model_dump()},
                {},
                "",
                live2d_model=FakeLive2DModel(),
            )
            self.assertEqual(agent._streaming_output, not option)
