import unittest

from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision
from open_llm_vtuber.mental_health.intent_estimator import IntentEstimator
from open_llm_vtuber.mental_health.schemas import (
    DecisionContext,
    DecisionResult,
    PsychologicalState,
    SafetyCheckResult,
    StrategyDecision,
)


class CoordinationTests(unittest.TestCase):
    def context(self, text, risk="low"):
        return DecisionContext(
            user_text=text,
            current_state=PsychologicalState(risk_level=risk),
            safety=SafetyCheckResult(
                action="escalate" if risk == "critical" else "allow", risk_level=risk
            ),
            interaction_intent=IntentEstimator().estimate(text),
        )

    def test_declined_advice_overrides_proposal_without_mutating_it(self):
        proposed = DecisionResult(
            strategy=StrategyDecision(
                primary="collaborative_problem_solving", secondary="offer_small_step"
            )
        )
        proposed.trace.source = "model"
        result = coordinate_decision(proposed, self.context("我只想倾诉，先别给建议"))
        self.assertEqual(result.strategy.primary, "supportive_listening")
        self.assertEqual(proposed.strategy.primary, "collaborative_problem_solving")
        self.assertEqual(result.trace.source, "model")
        trace = result.trace.coordination
        self.assertEqual(trace.proposed_strategy, "collaborative_problem_solving")
        self.assertEqual(trace.final_strategy, "supportive_listening")
        self.assertIn("advice_declined", trace.reason_codes)

    def test_end_overrides_history_and_explicit_risk_overrides_end(self):
        context = self.context("今天先聊到这里")
        context.long_term_trend = {"means": {"stress": 0.9}, "insufficient_data": False}
        result = coordinate_decision(DecisionResult(), context)
        self.assertEqual(result.strategy.primary, "close_supportively")
        self.assertEqual(result.strategy.secondary, "acknowledge_closure")
        risk = coordinate_decision(
            DecisionResult(), self.context("今天先聊到这里", "critical")
        )
        self.assertEqual(risk.strategy.primary, "crisis_support")

    def test_practical_request_and_repeated_listening(self):
        result = coordinate_decision(DecisionResult(), self.context("请给我一个办法"))
        self.assertEqual(result.strategy.primary, "collaborative_problem_solving")
        context = self.context("只想倾诉")
        context.previous_strategy = "supportive_listening"
        self.assertEqual(
            coordinate_decision(DecisionResult(), context).strategy.primary,
            "supportive_listening",
        )

    def test_unknown_does_not_force_strategy_and_trace_cannot_be_model_supplied(self):
        proposed = DecisionResult(
            strategy=StrategyDecision(primary="validate_and_ground")
        )
        result = coordinate_decision(proposed, self.context("嗯"))
        self.assertEqual(result.strategy.primary, "validate_and_ground")
        self.assertEqual(result.trace.coordination.reason_codes, [])
        self.assertNotIn("coordination", result.model_dump())
        with self.assertRaises(ValueError):
            DecisionResult.model_validate({**result.model_dump(), "coordination": {}})


if __name__ == "__main__":
    unittest.main()
