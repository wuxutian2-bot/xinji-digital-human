from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from open_llm_vtuber.mental_health.long_term import (
    TrendSettings,
    summarize_daily_trend,
    summarize_daily_trend_v3,
    trend_for_model,
)
from open_llm_vtuber.mental_health.schemas import (
    DecisionContext,
    InteractionIntent,
    PsychologicalState,
    SafetyCheckResult,
)
from open_llm_vtuber.mental_health.decision_client import (
    RuleBasedDecisionClient,
    OpenAICompatibleDecisionClient,
)
from open_llm_vtuber.mental_health.memory_service import format_memory_context
from open_llm_vtuber.mental_health.schemas import DecisionResult
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService

NOW = datetime(2026, 11, 15, 4, tzinfo=timezone.utc)


def state(day, score, source="context_v2"):
    return PsychologicalState(
        timestamp=NOW - timedelta(days=day),
        estimator_source=source,
        observed_dimensions=["stress"],
        emotion={"stress": score},
    )


def rising_rows():
    return [state(day, 0.2) for day in range(7, 14)] + [
        state(6 - i, value)
        for i, value in enumerate([0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8])
    ]


class DailyV3Tests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **kwargs):
        return TrendSettings(version="daily_v3", daily_v3=kwargs)

    def test_missing_and_single_day_have_no_interval_or_alert(self):
        empty = summarize_daily_trend_v3([], NOW)
        self.assertTrue(empty.insufficient_data)
        self.assertIsNone(empty.means["stress"])
        for rows in ([], [state(0, 0.9)] * 20):
            metric = (
                summarize_daily_trend_v3(rows, NOW)
                .sources["system_estimate"]
                .dimensions["stress"]
            )
            self.assertIsNone(metric.interval80)
            self.assertIsNone(metric.alert)
            self.assertFalse(metric.eligible_for_decision)
        result = summarize_daily_trend_v3([state(0, 0.9)], NOW)
        self.assertNotIn(
            str((NOW - timedelta(days=1)).date()),
            result.sources["system_estimate"].dimensions["stress"].daily_smoothed,
        )
        self.assertIsNone(
            trend_for_model(result.model_dump(mode="json"))["decision_dimensions"][
                "stress"
            ]["mean"]
        )

    def test_rising_is_deterministic_calendar_weighted_and_deduplicated(self):
        rows = rising_rows()
        settings = self.settings(bootstrap_samples=200)
        result = summarize_daily_trend_v3(rows, NOW, settings)
        metric = result.sources["system_estimate"].dimensions["stress"]
        self.assertEqual(metric.alert, "rising")
        self.assertEqual(metric.alert_started_at, "2026-11-09")
        expected = sum(
            row.emotion.stress * 2 ** (-(NOW - row.timestamp).days / 3)
            for row in rows
            if (NOW - row.timestamp).days < 7
        ) / sum(2 ** (-day / 3) for day in range(7))
        self.assertAlmostEqual(metric.weighted_mean, expected, places=5)
        self.assertEqual(
            result.sources,
            summarize_daily_trend_v3(
                list(reversed(rows)) + [rows[-1]] * 30, NOW, settings
            ).sources,
        )
        self.assertTrue(0 <= metric.interval80[0] <= metric.interval80[1] <= 1)
        self.assertGreater(
            metric.weighted_mean,
            summarize_daily_trend_v3(
                rows, NOW, self.settings(half_life_days=30, bootstrap_samples=200)
            )
            .sources["system_estimate"]
            .dimensions["stress"]
            .weighted_mean,
        )

    def test_stable_spike_gap_and_old_data_do_not_report_continuous_rising(self):
        baseline = [state(day, 0.2) for day in range(7, 14)]
        cases = [
            [state(day, 0.2) for day in range(7)],
            [state(0, 0.9), state(1, 0.2), state(2, 0.2)],
            [state(0, 0.9), state(2, 0.8), state(4, 0.7)],
        ]
        for rows in cases:
            self.assertIsNone(
                summarize_daily_trend_v3(baseline + rows, NOW)
                .sources["system_estimate"]
                .dimensions["stress"]
                .alert
            )
        old = summarize_daily_trend_v3([state(i, 0.8) for i in (8, 9, 10)], NOW)
        projected = trend_for_model(old.model_dump(mode="json"))
        self.assertIsNone(projected["decision_dimensions"]["stress"]["mean"])
        flat = summarize_daily_trend_v3([state(i, 0) for i in range(14)], NOW)
        metric = flat.sources["system_estimate"].dimensions["stress"]
        self.assertEqual(metric.interval80, (0, 0))
        self.assertIsNone(metric.alert)

    async def test_disagreement_prefers_user_report_without_overriding_safety_or_intent(
        self,
    ):
        rows = [state(i, 0.9) for i in range(7)] + [
            state(i, 0.1, "user_report") for i in range(3)
        ]
        trend = summarize_daily_trend_v3(rows, NOW)
        self.assertTrue(
            trend.sources["system_estimate"].dimensions["stress"].source_disagreement
        )
        self.assertEqual(trend.preferred_sources["stress"], "user_report")
        projected = trend_for_model(trend.model_dump(mode="json"))
        self.assertEqual(projected["decision_dimensions"]["stress"]["mean"], 0.1)
        self.assertIsNone(projected["sources"]["system_estimate"]["stress"]["mean"])
        context = DecisionContext(
            user_text="普通发言",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
            long_term_trend=trend.model_dump(mode="json"),
        )
        client = RuleBasedDecisionClient()
        proposal = await client.decide(context)
        self.assertEqual(proposal.strategy.primary, "supportive_listening")
        context.interaction_intent = InteractionIntent(
            primary="seeking_practical_help",
            advice_preference="requested",
            certainty="explicit",
        )
        self.assertEqual(
            coordinate_decision(proposal, context).strategy.primary,
            "collaborative_problem_solving",
        )
        context.safety = SafetyCheckResult(action="escalate", risk_level="high")
        self.assertEqual(
            coordinate_decision(proposal, context).strategy.primary, "crisis_support"
        )
        one = summarize_daily_trend_v3(
            [state(i, 0.9) for i in range(7)] + [state(0, 0.1, "user_report")], NOW
        )
        self.assertIsNone(
            trend_for_model(one.model_dump(mode="json"))["decision_dimensions"][
                "stress"
            ]["mean"]
        )

    async def test_normal_sqlite_entry_point_uses_v3(self):
        with TemporaryDirectory() as folder:
            memory = SqlitePsychologicalMemoryService(
                str(Path(folder) / "state.db"),
                "synthetic",
                trend_settings=self.settings(bootstrap_samples=200),
            )
            for row in rising_rows():
                await memory.append("test", row)
            trend = await memory.retrieve_trend(NOW)
            self.assertEqual(trend.version, "daily_v3")
            context = DecisionContext(
                user_text="普通发言",
                current_state=PsychologicalState(),
                safety=SafetyCheckResult(action="allow"),
                long_term_trend=trend.model_dump(mode="json"),
            )
            proposal = await RuleBasedDecisionClient().decide(context)
            self.assertEqual(proposal.strategy.primary, "reflect_and_clarify")
            self.assertEqual(
                coordinate_decision(proposal, context).trace.coordination.winner_role,
                "history",
            )

    async def test_alert_drives_clarification_below_the_absolute_threshold(self):
        rows = [state(i, 0.05) for i in range(7, 14)] + [
            state(6 - i, value)
            for i, value in enumerate([0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4])
        ]
        trend = summarize_daily_trend_v3(rows, NOW)
        self.assertLess(trend.means["stress"], 0.6)
        context = DecisionContext(
            user_text="普通发言",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
            long_term_trend=trend.model_dump(mode="json"),
        )
        proposal = await RuleBasedDecisionClient().decide(context)
        self.assertEqual(proposal.strategy.primary, "reflect_and_clarify")
        result = coordinate_decision(proposal, context)
        self.assertIn("history_rising", result.trace.coordination.reason_codes)

    async def test_remote_and_dialogue_contexts_cannot_bypass_source_preference(self):
        rows = [state(i, 0.9) for i in range(7)] + [
            state(i, 0.1, "user_report") for i in range(3)
        ]
        trend = summarize_daily_trend_v3(rows, NOW)
        create = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=DecisionResult().model_dump_json()
                        ),
                        finish_reason="stop",
                    )
                ]
            )
        )
        sdk = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        client = OpenAICompatibleDecisionClient(
            model="test", base_url="http://localhost/v1", llm_api_key="test", client=sdk
        )
        context = DecisionContext(
            user_text="普通发言",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
            long_term_trend=trend.model_dump(mode="json"),
            recent_states=[state(0, 1)],
        )
        await client.decide(context)
        messages = create.call_args.kwargs["messages"]
        request = json.loads(messages[1]["content"])
        self.assertEqual(request["recent_states"], [])
        projected = request["long_term_trend"]
        self.assertIsNone(projected["sources"]["system_estimate"]["stress"]["mean"])
        self.assertEqual(projected["decision_dimensions"]["stress"]["mean"], 0.1)
        dialogue = format_memory_context(
            context.current_state, context.recent_states, trend
        )
        self.assertNotIn("Recent observed estimates", dialogue)
        self.assertIn('"source": "user_report"', dialogue)

    def test_disagreement_threshold_is_strictly_greater_than_point_three(self):
        trend = summarize_daily_trend_v3(
            [state(i, 0.6) for i in range(3)]
            + [state(i, 0.3, "user_report") for i in range(3)],
            NOW,
        )
        self.assertFalse(trend.source_disagreement["stress"])

    def test_frozen_fourteen_day_fixture_keeps_v2_results(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures/daily_v3_14_day.json").read_text("utf8")
        )
        rows = [
            PsychologicalState(
                timestamp=r["timestamp"],
                estimator_source="user_correction"
                if "correction" in r
                else r["source"],
                observed_dimensions=["stress"],
                emotion={"stress": r.get("correction", r["stress_input"])},
            )
            for r in fixture["records"]
        ]
        now = datetime.fromisoformat(fixture["trend"]["as_of"].replace("Z", "+00:00"))
        baseline = summarize_daily_trend(
            rows, now, TrendSettings(**fixture["trend"]["settings"])
        )
        self.assertEqual(baseline.model_dump(mode="json"), fixture["trend"])
        v3 = summarize_daily_trend_v3(rows, now)
        self.assertEqual(
            v3.sources["user_report"].dimensions["stress"].observed_days, 4
        )
        self.assertEqual(
            v3.sources["system_estimate"].dimensions["stress"].daily_means,
            baseline.sources["system_estimate"].dimensions["stress"].daily_means,
        )
