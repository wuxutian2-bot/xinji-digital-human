import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_llm_vtuber.mental_health.decision_client import RuleBasedDecisionClient
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision
from open_llm_vtuber.mental_health.schemas import (
    AgentProposal,
    CoordinationTrace,
    DecisionContext,
    DecisionResult,
    InteractionIntent,
    PsychologicalState,
    SafetyCheckResult,
)
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
import test_mental_health_agent as fixtures


class ArbitrationTraceTests(unittest.IsolatedAsyncioTestCase):
    def context(self, **changes):
        return DecisionContext(
            user_text="sensitive-original-sentinel",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
            **changes,
        )

    async def test_every_priority_branch_records_its_winner(self):
        cases = [
            ({"primary": "ending"}, "safety", "crisis_support", True, False),
            (
                {"primary": "ending", "advice_preference": "declined"},
                "intent",
                "close_supportively",
                False,
                False,
            ),
            (
                {
                    "feedback": "unhelpful",
                    "source": "user_control",
                    "advice_preference": "declined",
                },
                "feedback",
                "reflect_and_clarify",
                False,
                False,
            ),
            (
                {"advice_preference": "declined", "primary": "seeking_practical_help"},
                "intent",
                "supportive_listening",
                False,
                False,
            ),
            (
                {
                    "primary": "venting",
                    "feedback": "unhelpful",
                    "source": "current_turn",
                },
                "intent",
                "supportive_listening",
                False,
                False,
            ),
            (
                {"primary": "seeking_practical_help", "advice_preference": "requested"},
                "intent",
                "collaborative_problem_solving",
                False,
                False,
            ),
            (
                {"primary": "seeking_clarification"},
                "intent",
                "reflect_and_clarify",
                False,
                False,
            ),
            (
                {"feedback": "unhelpful", "source": "current_turn"},
                "feedback",
                "reflect_and_clarify",
                False,
                False,
            ),
            ({}, "safety", "supportive_listening", False, True),
            ({}, "decision_model", "supportive_listening", False, False),
        ]
        for intent, role, strategy, crisis, boundary in cases:
            with self.subTest(intent=intent, crisis=crisis, boundary=boundary):
                context = self.context(
                    interaction_intent=InteractionIntent(**intent),
                    protocol_control_detected=boundary,
                )
                if crisis:
                    context.safety = SafetyCheckResult(
                        action="escalate", risk_level="high"
                    )
                    context.long_term_trend = {"version": "daily_v2"}
                proposed = DecisionResult()
                before = proposed.model_dump()
                result = coordinate_decision(proposed, context)
                trace = result.trace.coordination
                self.assertEqual(
                    (trace.winner_role, result.strategy.primary), (role, strategy)
                )
                self.assertEqual(
                    {p.role for p in trace.proposals},
                    {
                        "safety",
                        "state",
                        "intent",
                        "feedback",
                        "history",
                        "decision_model",
                    },
                )
                self.assertEqual(proposed.model_dump(), before)
                self.assertNotIn(context.user_text, trace.model_dump_json())

    async def test_rule_state_history_and_remote_model_have_distinct_winners(self):
        state = self.context()
        state.current_state = PsychologicalState(
            emotion={"stress": 0.8}, observed_dimensions=["stress"]
        )
        history = self.context(
            long_term_trend={
                "insufficient_data": False,
                "means": {"stress": 0.8},
                "observed_counts": {"stress": 3},
            }
        )
        for context, role in ((state, "state"), (history, "history")):
            proposal = await RuleBasedDecisionClient().decide(context)
            result = coordinate_decision(proposal, context)
            self.assertEqual(result.trace.coordination.winner_role, role)
            proposal.trace.source = "model"
            result = coordinate_decision(proposal, context)
            self.assertEqual(result.trace.coordination.winner_role, "decision_model")
            self.assertIn(
                "decision_model_proposal",
                result.trace.coordination.proposals[-1].evidence_codes,
            )

    async def test_safety_bypass_and_midstream_override_are_persisted(self):
        helper = fixtures.MentalHealthAgentTests()
        with TemporaryDirectory() as folder:
            for text, response in (
                ("我不想活了", "我在听。"),
                ("我想聊一会儿", "第一句。你应该去死。"),
            ):
                dialogue = fixtures.FakeDialogueClient(response)
                agent = helper._agent(dialogue, Path(folder) / "memory.jsonl")
                request = BatchInput(
                    texts=[TextData(source=TextSource.INPUT, content=text)]
                )
                _ = [o async for o in agent.chat(request)]
                record = (
                    await agent._psychological_memory.retrieve_recent(
                        agent._psychological_memory_scope
                    )
                )[-1]
                self.assertEqual(
                    record.decision_trace.coordination.winner_role, "safety"
                )
                self.assertTrue(
                    any(
                        p.role == "safety"
                        for p in record.decision_trace.coordination.proposals
                    )
                )
                if text == "我不想活了":
                    self.assertEqual(dialogue.calls, 0)
                else:
                    self.assertTrue(record.decision_trace.output_safety_override)

    def test_legacy_audit_and_evidence_validation(self):
        trace = CoordinationTrace(
            proposed_strategy="supportive_listening",
            final_strategy="supportive_listening",
            winner_role="intent",
            proposals=[
                AgentProposal(role="intent", evidence_codes=["advice_declined"])
            ],
        )
        old = trace.model_dump(exclude={"winner_role", "proposals"})
        self.assertTrue(trace.matches_recorded(old))
        self.assertEqual(CoordinationTrace.model_validate(old).proposals, [])
        changed = json.loads(trace.model_dump_json())
        changed["winner_role"] = "safety"
        self.assertFalse(trace.matches_recorded(changed))
        with self.assertRaises(ValueError):
            AgentProposal(role="intent", evidence_codes=["raw user words"])
