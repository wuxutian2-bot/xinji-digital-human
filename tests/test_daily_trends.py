from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from open_llm_vtuber.mental_health.long_term import (
    TrendSettings,
    summarize_daily_trend,
    summarize_trend,
    trend_for_model,
)
from open_llm_vtuber.mental_health.schemas import (
    DecisionContext,
    DecisionResult,
    SafetyCheckResult,
    PsychologicalState,
    UserStateReport,
)
from open_llm_vtuber.mental_health.decision_client import (
    RuleBasedDecisionClient,
    OpenAICompatibleDecisionClient,
)
from open_llm_vtuber.mental_health.memory_service import format_memory_context
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService


NOW = datetime(2026, 9, 23, 4, tzinfo=timezone.utc)


def state(days=0, score=0.8, **kwargs):
    return PsychologicalState(
        timestamp=NOW - timedelta(days=days),
        estimator_source="context_v2",
        observed_dimensions=["stress"],
        emotion={"stress": score},
        topics=["work", "work"],
        **kwargs,
    )


class DailyTrendTests(unittest.TestCase):
    def test_equal_day_weight_and_exact_replay_invariance(self):
        rows = [state(0, 1), state(1, 0), state(2, 0)]
        baseline = summarize_daily_trend(rows, NOW)
        duplicated = summarize_daily_trend(rows + [rows[0]] * 99, NOW)
        self.assertEqual(baseline.sources, duplicated.sources)
        self.assertEqual(duplicated.means["stress"], 0.333)
        self.assertEqual(
            summarize_trend(rows + [rows[0]] * 99, NOW).means["stress"], 0.98
        )
        # Distinct observations within one day change that day's mean only.
        extra = rows[0].model_copy(update={"timestamp": NOW - timedelta(hours=1)})
        self.assertEqual(
            summarize_daily_trend(rows + [extra] * 99, NOW).means["stress"], 0.333
        )

    def test_calendar_boundaries_future_cutoff_coverage_and_changes(self):
        rows = [state(i, 0.8 if i < 7 else 0.2) for i in (0, 1, 6, 7, 8, 13)]
        rows += [
            state(-1, 1),
            state(14, 1),
            state().model_copy(update={"timestamp": NOW + timedelta(seconds=1)}),
        ]
        result = summarize_daily_trend(rows, NOW)
        self.assertEqual(result.sample_count, 3)
        self.assertEqual(result.previous_sample_count, 3)
        self.assertEqual(result.changes["stress"], 0.6)
        metric = result.sources["system_estimate"].dimensions["stress"]
        self.assertEqual(metric.observed_days, 3)
        self.assertEqual(metric.coverage, 0.429)
        self.assertEqual(metric.age_days, 0)
        self.assertEqual(
            result.current_window.start.isoformat(), "2026-09-17T00:00:00+08:00"
        )
        self.assertEqual(
            result.previous_window.end_exclusive, result.current_window.start
        )
        self.assertEqual(result.recurring_topics, ["work"])

    def test_partial_unknown_zero_stale_and_legacy(self):
        rows = [
            state(30, 1),
            state().model_copy(update={"estimator_source": "legacy"}),
            state().model_copy(update={"timestamp": NOW.replace(tzinfo=None)}),
            state().model_copy(update={"timestamp_known": False}),
        ]
        result = summarize_daily_trend(rows, NOW)
        dim = result.sources["system_estimate"].dimensions["stress"]
        self.assertTrue(dim.stale)
        self.assertEqual(dim.age_days, 30)
        self.assertEqual(dim.last_observed_at, rows[0].timestamp)
        self.assertIsNone(dim.mean)
        self.assertEqual(dim.observed_days, 0)
        self.assertEqual(result.excluded_records["unknown_source"], 1)
        self.assertEqual(result.excluded_records["unknown_time"], 2)
        self.assertIsNone(result.means["anxiety"])
        zero = summarize_daily_trend([state(i, 0) for i in (0, 1, 2)], NOW)
        self.assertEqual(zero.means["stress"], 0)
        self.assertFalse(zero.insufficient_data)
        self.assertFalse(dim.eligible_for_decision)
        self.assertIsNone(
            trend_for_model(result.model_dump(mode="json"))["sources"][
                "system_estimate"
            ]["stress"]["mean"]
        )

    def test_one_day_is_not_three_days_and_sources_never_pool(self):
        rows = [
            state().model_copy(update={"timestamp": NOW - timedelta(minutes=i)})
            for i in range(5)
        ]
        rows += [state(8), state(9), state(10)]
        result = summarize_daily_trend(rows, NOW)
        self.assertIsNone(result.changes["stress"])
        self.assertEqual(result.recurring_topics, [])
        self.assertTrue(result.insufficient_data)
        rows += [
            state(i, 0).model_copy(update={"estimator_source": "user_report"})
            for i in (0, 1, 2)
        ]
        result = summarize_daily_trend(rows, NOW)
        self.assertEqual(result.sources["user_report"].dimensions["stress"].mean, 0)
        self.assertEqual(result.means["stress"], 0.8)
        self.assertFalse(
            result.sources["system_estimate"].dimensions["stress"].eligible_for_decision
        )

    def test_timezone_midnight_and_dst_are_calendar_dates(self):
        midnight = datetime.fromisoformat("2026-09-23T00:01:00+08:00")
        rows = [
            state().model_copy(update={"timestamp": midnight - timedelta(minutes=i)})
            for i in (0, 2)
        ]
        self.assertEqual(
            summarize_daily_trend(rows, midnight)
            .sources["system_estimate"]
            .dimensions["stress"]
            .observed_days,
            2,
        )
        utc = TrendSettings(version="daily_v2", timezone="UTC")
        self.assertEqual(
            summarize_daily_trend(rows, midnight, utc)
            .sources["system_estimate"]
            .dimensions["stress"]
            .observed_days,
            1,
        )
        settings = TrendSettings(version="daily_v2", timezone="America/New_York")
        now = datetime.fromisoformat("2026-03-09T12:00:00-04:00")
        trend = summarize_daily_trend([], now, settings)
        elapsed = trend.current_window.end_exclusive.astimezone(
            timezone.utc
        ) - trend.current_window.start.astimezone(timezone.utc)
        self.assertEqual(elapsed.total_seconds() / 3600, 167)
        now = datetime.fromisoformat("2026-11-02T12:00:00-05:00")
        trend = summarize_daily_trend([], now, settings)
        elapsed = trend.current_window.end_exclusive.astimezone(
            timezone.utc
        ) - trend.current_window.start.astimezone(timezone.utc)
        self.assertEqual(elapsed.total_seconds() / 3600, 169)

    def test_settings_and_self_report_validation(self):
        for settings in (
            {"timezone": "Missing/Zone"},
            {"min_observed_days": 0},
            {"min_topic_days": 8},
        ):
            with self.assertRaises(ValueError):
                TrendSettings(**settings)
        for report in (
            {"timestamp": NOW, "emotion": {}},
            {"timestamp": NOW.replace(tzinfo=None), "emotion": {"stress": 0}},
            {"timestamp": NOW, "emotion": {"stress": 2}},
            {"timestamp": NOW, "emotion": {"other": 0}},
        ):
            with self.assertRaises(ValueError):
                UserStateReport(**report)


class DailyStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_rules_use_days_and_freshness_without_overriding_current_safety(self):
        rules = RuleBasedDecisionClient()
        context = DecisionContext(
            user_text="hello",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
        )
        for rows, expected in (
            ([state()] * 100, "supportive_listening"),
            ([state(i) for i in (0, 1, 2)], "reflect_and_clarify"),
            ([state(i) for i in (8, 9, 10)], "supportive_listening"),
        ):
            context.long_term_trend = summarize_daily_trend(rows, NOW).model_dump(
                mode="json"
            )
            self.assertEqual((await rules.decide(context)).strategy.primary, expected)
        settings = TrendSettings(
            version="daily_v2", min_observed_days=1, stale_after_days=0
        )
        context.long_term_trend = summarize_daily_trend(
            [state(1)], NOW, settings
        ).model_dump(mode="json")
        self.assertEqual(
            (await rules.decide(context)).strategy.primary, "supportive_listening"
        )
        context.current_state.risk_level = "high"
        self.assertEqual(
            (await rules.decide(context)).strategy.primary, "ensure_immediate_safety"
        )

    async def test_model_context_withholds_stale_scores_and_keeps_sources_separate(
        self,
    ):
        trend = summarize_daily_trend([state(i) for i in (0, 1, 2)], NOW)
        current = PsychologicalState()
        recent = [state(30, 1)]
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
        client = OpenAICompatibleDecisionClient(
            model="test",
            base_url="http://localhost/v1",
            llm_api_key="test",
            client=SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create))
            ),
        )
        context = DecisionContext(
            user_text="hello",
            current_state=current,
            recent_states=recent,
            safety=SafetyCheckResult(action="allow"),
            long_term_trend=trend.model_dump(mode="json"),
        )
        await client.decide(context)
        payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["recent_states"], [])
        self.assertEqual(len(context.recent_states), 1)
        self.assertEqual(
            payload["long_term_trend"]["sources"]["system_estimate"]["stress"]["mean"],
            0.8,
        )
        self.assertNotIn(
            "daily_means", create.call_args.kwargs["messages"][1]["content"]
        )
        text = format_memory_context(current, recent, trend)
        self.assertNotIn("Recent observed estimates", text)
        self.assertIn("daily_v2", text)
        stale = summarize_daily_trend([state(i) for i in (8, 9, 10)], NOW)
        context.long_term_trend = stale.model_dump(mode="json")
        await client.decide(context)
        payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
        self.assertNotIn("mean", payload["recent_states"])
        self.assertEqual(
            payload["long_term_trend"]["sources"]["system_estimate"]["stress"][
                "status"
            ],
            "stale",
        )
        self.assertNotIn("0.8", create.call_args.kwargs["messages"][1]["content"])

    async def test_corrections_deletions_source_provenance_and_restart(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "state.db")
            settings = TrendSettings(version="daily_v2")
            store = SqlitePsychologicalMemoryService(
                path, "owner", trend_settings=settings
            )
            for i in (0, 1, 2):
                item = state(i)
                item.emotion.anxiety = 0.4
                item.observed_dimensions.append("anxiety")
                await store.append("h", item)
            before = store.list_records()[0]
            store.correct(before["id"], {"summary": "edited"})
            self.assertEqual((await store.retrieve_trend(NOW)).means["stress"], 0.8)
            store.correct(before["id"], {"emotion": {"stress": 0}})
            result = await store.retrieve_trend(NOW)
            self.assertEqual(
                result.sources["system_estimate"].dimensions["stress"].observed_days, 2
            )
            self.assertEqual(
                result.sources["system_estimate"].dimensions["anxiety"].observed_days, 3
            )
            self.assertEqual(
                result.sources["user_correction"].dimensions["stress"].mean, 0
            )
            after = store.list_records()[0]
            self.assertEqual(after["state"]["timestamp"], before["state"]["timestamp"])
            self.assertEqual(after["history_scope"], "h")
            snapshot = after["state"]
            with self.assertRaises(ValueError):
                store.correct(before["id"], {"emotion": {"stress": 9}})
            self.assertEqual(store.list_records()[0]["state"], snapshot)
            other = SqlitePsychologicalMemoryService(
                path, "other", trend_settings=settings
            )
            self.assertFalse(other.correct(before["id"], {"emotion": {"stress": 1}}))
            self.assertEqual(other.delete(record_id=before["id"]), 0)
            self.assertTrue((await other.retrieve_trend(NOW)).insufficient_data)
            store.delete(record_id=before["id"])
            restarted = SqlitePsychologicalMemoryService(
                path, "owner", trend_settings=settings
            )
            self.assertIsNone(
                (await restarted.retrieve_trend(NOW))
                .sources["user_correction"]
                .dimensions["stress"]
                .mean
            )

    async def test_missing_import_time_never_becomes_observed_today(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)
            source = path / "old.jsonl"
            source.write_text(
                '{"scope":"h","state":{"estimator_source":"keyword_v1","observed_dimensions":["stress"],"emotion":{"stress":1}}}',
                encoding="utf-8",
            )
            store = SqlitePsychologicalMemoryService(
                str(path / "state.db"),
                "u",
                trend_settings=TrendSettings(version="daily_v2"),
            )
            store.import_jsonl(source, {"h"})
            self.assertIsNone((await store.retrieve_trend()).means["stress"])
