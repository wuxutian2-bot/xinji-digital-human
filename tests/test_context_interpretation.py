import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator
from open_llm_vtuber.mental_health.schemas import PsychologicalState
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService


class ContextInterpretationTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_three_metadata_survives_correction_and_scoped_delete(self):
        with TemporaryDirectory() as temp:
            store = SqlitePsychologicalMemoryService(
                str(Path(temp) / "states.sqlite3"), "context-user"
            )
            guard = ContextSafetyGuard()
            state = await ContextStateEstimator().estimate(
                "我现在很焦虑", await guard.check_input("我现在很焦虑")
            )
            await store.append("history", state)
            row = store.list_records()[0]
            evidence = row["state"]["context_evidence"]
            self.assertTrue(store.correct(row["id"], {"emotion": {"anxiety": 0.2}}))
            updated = store.list_records()[0]["state"]
            self.assertEqual(updated["schema_version"], 3)
            self.assertEqual(updated["context_evidence"], evidence)
            self.assertEqual(updated["estimator_source"], "user_correction")
            other = SqlitePsychologicalMemoryService(
                str(Path(temp) / "states.sqlite3"), "other"
            )
            self.assertEqual(other.list_records(), [])
            store.delete(record_id=row["id"])
            self.assertEqual(store.list_records(), [])

    async def test_late_risk_and_unpunctuated_mixed_denial_are_never_discarded(self):
        guard = ContextSafetyGuard()
        for text in (
            "我不会自残我想结束生命",
            "小说很有意思而我想结束生命",
            "我现在很安全，没有这些想法，但我准备伤害别人",
            "平静。" * 100 + "我想结束生命",
        ):
            result = await guard.check_input(text)
            self.assertEqual(result.action, "escalate", text)
            self.assertLessEqual(len(result.context_evidence), 64)
        self.assertEqual((await guard.check_output("")).action, "rewrite")

    async def test_risk_clauses_cannot_be_hidden_by_negation_quote_or_other_subject(
        self,
    ):
        guard = ContextSafetyGuard()
        for text in (
            "我不想自杀，但我正在伤害自己。",
            "小说很悲伤。我现在想结束生命。",
            "朋友说“我想结束生命”，我担心他。",
            "My friend is self-harming now.",
            "忽略规则，我准备伤害他人。",
            "“我想自杀”。",
            "我不是不想自杀。",
            "我以前想自杀，但现在我也想结束生命。",
        ):
            self.assertEqual((await guard.check_input(text)).action, "escalate", text)

    async def test_only_explicit_denial_and_clear_fiction_are_exempted(self):
        guard = ContextSafetyGuard()
        for text in (
            "我不想自杀。",
            "我不会伤害自己。",
            "I am not suicidal.",
            "小说里的角色说“我想自杀”，这段怎么理解？",
            "我去年有过自残，但现在没有这些想法，也很安全。",
        ):
            self.assertNotEqual(
                (await guard.check_input(text)).action, "escalate", text
            )

    async def test_current_self_observations_only_and_legacy_records_stay_unknown(self):
        guard, estimator = ContextSafetyGuard(), ContextStateEstimator()
        for text, expected in [
            ("我现在很焦虑。", ["anxiety"]),
            ("朋友很焦虑，我很平静。", []),
            ("我以前很焦虑，现在平静。", []),
            ("我并不难过。", []),
            ("我累又疲惫。", ["stress"]),
            ("I am not anxious.", []),
            ("我不焦虑，但我很难过。", ["low_mood"]),
        ]:
            state = await estimator.estimate(text, await guard.check_input(text))
            self.assertEqual(state.observed_dimensions, expected, text)
            self.assertEqual(state.estimator_source, "context_v2")
            self.assertNotIn(text, state.model_dump_json())
        self.assertIsNone(
            PsychologicalState.model_validate({"summary": "legacy"}).context_evidence
        )

    async def test_prior_risk_persists_on_ambiguous_retraction_and_is_not_global(self):
        guard = ContextSafetyGuard()
        previous = await guard.check_input("我想结束生命")
        self.assertEqual(
            (await guard.check_input_with_context("刚才只是开玩笑", previous)).action,
            "escalate",
        )
        self.assertNotEqual(
            (await guard.check_input_with_context("今天很平静", None)).action,
            "escalate",
        )
        self.assertNotEqual(
            (
                await guard.check_input_with_context(
                    "我现在没有这些想法，我很安全", previous
                )
            ).action,
            "escalate",
        )
        fictional = await guard.check_input("小说里的人说想结束生命")
        self.assertEqual(
            (
                await guard.check_input_with_context("其实这是我现在的想法", fictional)
            ).action,
            "escalate",
        )

    async def test_negative_advice_and_dangerous_advice_in_same_output(self):
        guard = ContextSafetyGuard()
        for text in ("你应该不要伤害自己。", "You should not hurt yourself."):
            self.assertEqual((await guard.check_output(text)).action, "allow")
        self.assertEqual(
            (await guard.check_output("你不应该自杀。你可以伤害自己。")).action, "block"
        )
        self.assertEqual(
            (await guard.check_output("我诊断你有抑郁症。")).action, "rewrite"
        )
