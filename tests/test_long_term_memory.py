import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_llm_vtuber.mental_health.decision_client import RuleBasedDecisionClient
from open_llm_vtuber.mental_health.long_term import summarize_trend
from open_llm_vtuber.mental_health.schemas import (
    DecisionContext,
    PsychologicalState,
    SafetyCheckResult,
)
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from open_llm_vtuber.config_manager.agent import MentalHealthMemoryConfig


class LongTermTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_correction_is_user_scoped_and_preserves_execution_facts(
        self,
    ):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "state.db")
            owner = SqlitePsychologicalMemoryService(path, "a")
            other = SqlitePsychologicalMemoryService(path, "b")
            await owner.append(
                "h",
                PsychologicalState(
                    interaction_intent={
                        "feedback": "unhelpful",
                        "feedback_source": "current_turn",
                    }
                ),
            )
            before = owner.list_records()[0]
            self.assertFalse(
                other.correct(before["id"], {"interaction_feedback": "helpful"})
            )
            self.assertTrue(
                owner.correct(before["id"], {"interaction_feedback": "helpful"})
            )
            state = owner.list_records()[0]["state"]
            self.assertEqual(state["interaction_intent"]["feedback"], "helpful")
            self.assertEqual(
                state["interaction_intent"]["feedback_source"], "user_correction"
            )
            for key in (
                "emotion",
                "timestamp",
                "decision_trace",
                "confidence",
                "estimator_source",
            ):
                self.assertEqual(state[key], before["state"][key])
            with self.assertRaises(ValueError):
                owner.correct(before["id"], {"interaction_feedback": "arbitrary"})
            self.assertEqual(owner.list_records()[0]["state"], state)
            self.assertEqual(owner.delete(record_id=before["id"]), 1)
            self.assertEqual(owner.list_records(), [])

    def test_local_user_requires_explicit_identity(self):
        for user_id in (None, "", " "):
            with self.assertRaises(ValueError):
                MentalHealthMemoryConfig(mode="local_user", user_id=user_id)

    def test_malformed_migration_does_not_partially_write(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.jsonl"
            path.write_text('{"scope":"owned","state":{}}\ninvalid', encoding="utf-8")
            store = SqlitePsychologicalMemoryService(str(Path(temp) / "state.db"), "a")
            with self.assertRaises(ValueError):
                store.import_jsonl(path, {"owned"})
            self.assertEqual(store.list_records(), [])

    async def test_cross_history_restart_user_isolation_and_concurrent_writes(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "state.db")
            first = SqlitePsychologicalMemoryService(path, "user-a")
            second = SqlitePsychologicalMemoryService(path, "user-b")
            await asyncio.gather(
                *[
                    first.append(f"history-{i}", PsychologicalState(summary=str(i)))
                    for i in range(10)
                ],
                second.append("history-0", PsychologicalState(summary="private-b")),
            )
            restarted = SqlitePsychologicalMemoryService(
                path, "user-a", recent_limit=20
            )
            rows = await restarted.retrieve_recent("new-history")
            self.assertEqual(len(rows), 10)
            self.assertNotIn("private-b", [row.summary for row in rows])
            self.assertEqual(len(await second.retrieve_recent("new-history")), 1)

    async def test_correction_and_delete_respect_owner_and_history(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "state.db")
            owner = SqlitePsychologicalMemoryService(path, "a")
            other = SqlitePsychologicalMemoryService(path, "b")
            await owner.append("h1", PsychologicalState(emotion={"anxiety": 0.7}))
            await owner.append("h2", PsychologicalState())
            record = owner.list_records(history_scope="h1")[0]["id"]
            self.assertFalse(other.correct(record, {"summary": "bad"}))
            self.assertEqual(other.delete(record_id=record), 0)
            self.assertTrue(owner.correct(record, {"emotion": {"stress": 0.2}}))
            changed = owner.list_records(history_scope="h1")[0]["state"]
            self.assertEqual(changed["emotion"]["anxiety"], 0.7)
            self.assertEqual(changed["emotion"]["stress"], 0.2)
            self.assertEqual(changed["estimator_source"], "user_correction")
            with self.assertRaises(ValueError):
                owner.correct(record, {"user_id": "b"})
            self.assertEqual(owner.delete(history_scope="h1"), 1)
            self.assertEqual(len(owner.list_records()), 1)
            self.assertEqual(owner.delete(), 1)
            self.assertEqual(owner.list_records(), [])

    def test_migration_requires_explicit_scopes_and_is_idempotent(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "old.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps({"scope": scope, "state": {"summary": scope}})
                    for scope in ("owned", "unknown")
                ),
                encoding="utf-8",
            )
            store = SqlitePsychologicalMemoryService(str(Path(temp) / "new.db"), "a")
            with self.assertRaises(ValueError):
                store.import_jsonl(source, set())
            self.assertEqual(store.import_jsonl(source, {"owned"}), 1)
            self.assertEqual(store.import_jsonl(source, {"owned"}), 0)
            self.assertEqual(store.list_records()[0]["state"]["schema_version"], 1)
            self.assertEqual(len(store.list_records()), 1)

    def test_unknown_is_not_zero_and_future_or_old_records_are_excluded(self):
        now = datetime.now(timezone.utc)
        trend = summarize_trend(
            [
                PsychologicalState(timestamp=now),
                PsychologicalState(
                    timestamp=now + timedelta(days=1),
                    emotion={"stress": 1},
                    observed_dimensions=["stress"],
                ),
                PsychologicalState(
                    timestamp=now - timedelta(days=30),
                    emotion={"stress": 1},
                    observed_dimensions=["stress"],
                ),
            ],
            now,
        )
        self.assertEqual(trend.sample_count, 1)
        self.assertIsNone(trend.means["stress"])
        self.assertIsNone(trend.changes["stress"])
        self.assertTrue(trend.insufficient_data)

    async def test_time_windows_affect_decision_for_same_current_input(self):
        now = datetime.now(timezone.utc)
        states = [
            PsychologicalState(
                timestamp=now - timedelta(days=i),
                emotion={"stress": 0.8},
                observed_dimensions=["stress"],
                topics=["work"],
            )
            for i in (1, 2, 3)
        ]
        states += [
            PsychologicalState(
                timestamp=now - timedelta(days=i),
                emotion={"stress": 0.2},
                observed_dimensions=["stress"],
            )
            for i in (8, 9, 10)
        ]
        trend = summarize_trend(states, now)
        self.assertEqual(trend.changes["stress"], 0.6)
        self.assertEqual(trend.recurring_topics, ["work"])
        context = DecisionContext(
            user_text="你好",
            current_state=PsychologicalState(),
            safety=SafetyCheckResult(action="allow"),
        )
        rules = RuleBasedDecisionClient()
        baseline = await rules.decide(context)
        context.long_term_trend = trend.model_dump()
        with_history = await rules.decide(context)
        self.assertEqual(baseline.strategy.primary, "supportive_listening")
        self.assertEqual(with_history.strategy.primary, "reflect_and_clarify")

    async def test_invalid_correction_is_transactional_and_trend_reads_corrected_values(
        self,
    ):
        with TemporaryDirectory() as temp:
            store = SqlitePsychologicalMemoryService(str(Path(temp) / "state.db"), "a")
            await store.append(
                "h1",
                PsychologicalState(
                    emotion={"stress": 0.8}, observed_dimensions=["stress"]
                ),
            )
            record = store.list_records()[0]["id"]
            with self.assertRaises(ValueError):
                store.correct(record, {"emotion": {"stress": 9}})
            self.assertEqual((await store.retrieve_trend()).means["stress"], 0.8)
            store.correct(record, {"emotion": {"stress": 0.0}})
            self.assertEqual((await store.retrieve_trend()).means["stress"], 0.0)
