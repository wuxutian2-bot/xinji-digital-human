import asyncio
import json
import httpx
from openai import APIConnectionError
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from open_llm_vtuber.mental_health.llm_estimator import (
    LLMStateIntentEstimator,
    resolve_estimated_intent,
)
from open_llm_vtuber.mental_health.intent_estimator import IntentEstimator
from open_llm_vtuber.mental_health.schemas import (
    RiskLevel,
    SafetyAction,
    SafetyCheckResult,
)
from open_llm_vtuber.mental_health.long_term import observation_source


class EstimatorTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = LLMStateIntentEstimator(
            "http://localhost:8000/v1", "test", "unused", 1
        )
        self.addAsyncCleanup(self.engine.aclose)
        self.create = AsyncMock()
        self.engine.client.chat.completions.create = self.create
        self.safety = SafetyCheckResult(
            action=SafetyAction.SUPPORT, risk_level=RiskLevel.ELEVATED
        )
        self.example = dict(
            stress=None,
            anxiety=0.35,
            low_mood=None,
            self_current=True,
            intent="venting",
            feedback="unspecified",
            advice_preference="unspecified",
        )

    async def extract(self, raw):
        self.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]
        )
        return await self.engine.estimate("我很担心上台。", self.safety)

    async def test_observed_and_rule_priority(self):
        state = await self.extract(json.dumps(self.example))
        self.assertEqual(state.observed_dimensions, ["anxiety"])
        self.assertIsNone(state.emotion.stress)
        self.assertEqual(state.risk_level, RiskLevel.ELEVATED)
        self.assertEqual(observation_source(state), "system_estimate")
        rule = IntentEstimator().estimate("给我一个建议")
        self.assertEqual(
            resolve_estimated_intent(rule, state.interaction_intent).primary,
            "seeking_practical_help",
        )
        self.assertEqual(
            (
                await self.extract(json.dumps(dict(self.example, self_current=False)))
            ).observed_dimensions,
            [],
        )

    async def test_invalid_payloads_fall_back(self):
        raw = json.dumps(self.example)
        for bad in (
            "{}",
            raw + "text",
            raw.replace('"stress":', '"stress": null, "stress":'),
            raw.replace("0.35", "1.1"),
            raw.replace("0.35", "true"),
            json.dumps(dict(self.example, risk_level="low")),
        ):
            with self.subTest(bad=bad):
                state = await self.extract(bad)
                self.assertEqual(state.estimator_source, "context_v2")
                self.assertEqual(state.estimator_fallback_reason, "invalid_response")
                self.assertEqual(state.risk_level, self.safety.risk_level)

    async def test_timeout_and_crisis(self):
        self.create.side_effect = asyncio.TimeoutError
        state = await self.engine.estimate("我很紧张", self.safety)
        self.assertEqual(state.estimator_fallback_reason, "timeout")
        self.create.reset_mock()
        crisis = SafetyCheckResult(
            action=SafetyAction.ESCALATE, risk_level=RiskLevel.CRITICAL
        )
        state = await self.engine.estimate("我不安全", crisis)
        self.create.assert_not_called()
        self.assertEqual(state.risk_level, RiskLevel.CRITICAL)

    async def test_api_failure_preserves_rule_intent_and_prior_preference(self):
        self.create.side_effect = APIConnectionError(
            request=httpx.Request("POST", "http://localhost")
        )
        state = await self.engine.estimate("我很紧张", self.safety)
        self.assertEqual(state.estimator_fallback_reason, "api_error")
        rule = IntentEstimator().estimate("别给我建议")
        self.assertEqual(resolve_estimated_intent(rule, state.interaction_intent), rule)
        previous = IntentEstimator().estimate("先聊聊", rule)
        self.create.side_effect = None
        state = await self.extract(json.dumps(self.example))
        combined = resolve_estimated_intent(previous, state.interaction_intent)
        self.assertEqual(combined.advice_preference, "declined")
        self.assertEqual(combined.preference_source, "recent_turn")
