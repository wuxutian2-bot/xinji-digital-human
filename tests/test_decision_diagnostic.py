import copy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "diagnostic", ROOT / "scripts/diagnose_decision.py"
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)
sys.path.insert(0, str(ROOT / "scripts"))
import export_decision_diagnostic as exporter  # noqa: E402


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = json.loads(
            (ROOT / "tests/fixtures/decision_diagnostic_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.cases = {c["id"]: c for c in self.fixture["cases"]}
        self.contexts = {
            k: await diagnostic.build_context(
                c, datetime.fromisoformat(self.fixture["now"])
            )
            for k, c in self.cases.items()
        }

    def sdk(self, primary="supportive_listening", finish="stop"):
        from open_llm_vtuber.mental_health.schemas import DecisionResult

        result = DecisionResult()
        result.strategy.primary = primary
        create = AsyncMock(
            return_value=SimpleNamespace(
                model=diagnostic.MODEL,
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=result.model_dump_json()),
                        finish_reason=finish,
                    )
                ],
            )
        )
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ), create

    async def test_factorial_changes_only_named_fields_and_preserves_grammar(self):
        sdk, create = self.sdk()
        await diagnostic.run_case(
            sdk, self.cases["d-help"], self.contexts["d-help"], "baseline"
        )
        request = create.call_args.kwargs
        original = copy.deepcopy(request)
        for variant in diagnostic.VARIANTS:
            changed = diagnostic.transform_request(request, variant)
            self.assertEqual(changed["response_format"], request["response_format"])
            self.assertEqual(changed["max_tokens"], request["max_tokens"])
            prompt = changed["messages"][0]["content"]
            self.assertEqual(
                '"default"' not in prompt, variant in {"no_schema_defaults", "both"}
            )
            context = json.loads(changed["messages"][1]["content"])
            self.assertEqual(
                "interaction_strategy" not in context["current_state"],
                variant in {"no_state_strategy", "both"},
            )
            expected = json.loads(request["messages"][1]["content"])
            if variant in {"no_state_strategy", "both"}:
                expected["current_state"].pop("interaction_strategy")
            self.assertEqual(context, expected)
        self.assertEqual(request, original)

    async def test_raw_parsed_and_coordinated_proposals_are_distinct(self):
        sdk, create = self.sdk()
        row = await diagnostic.run_case(
            sdk, self.cases["d-help"], self.contexts["d-help"], "both"
        )
        self.assertEqual(row["parsed"]["strategy"]["primary"], "supportive_listening")
        self.assertEqual(
            row["final"]["strategy"]["primary"], "collaborative_problem_solving"
        )
        self.assertFalse(row["proposed_match"])
        self.assertTrue(row["final_match"])
        self.assertEqual(
            json.loads(row["calls"][0]["raw_text"])["strategy"],
            row["parsed"]["strategy"],
        )
        create.assert_awaited_once()

    async def test_safety_bypasses_every_variant(self):
        sdk, create = self.sdk()
        for variant in diagnostic.VARIANTS:
            row = await diagnostic.run_case(
                sdk, self.cases["d-safety"], self.contexts["d-safety"], variant
            )
            self.assertEqual(row["source"], "safety_gate")
            self.assertEqual(row["calls"], [])
        create.assert_not_awaited()

    async def test_failure_is_not_counted_as_model_match(self):
        sdk, _ = self.sdk("collaborative_problem_solving", finish="length")
        row = await diagnostic.run_case(
            sdk, self.cases["d-help"], self.contexts["d-help"], "baseline"
        )
        self.assertEqual(row["source"], "fallback")
        self.assertIsNone(row["proposed_match"])
        metrics = diagnostic.aggregate([row])["baseline"]
        self.assertEqual(metrics["requests"], 1)
        self.assertEqual(metrics["valid"], 0)
        self.assertEqual(metrics["raw_proposal_distribution"], {})

    async def test_context_targets_and_history_are_frozen_and_not_labels_in_request(
        self,
    ):
        expected_intents = {
            "d-listen": "venting",
            "d-help": "seeking_practical_help",
            "d-close": "ending",
            "d-clarify": "seeking_clarification",
        }
        for identity, intent in expected_intents.items():
            self.assertEqual(self.contexts[identity].interaction_intent.primary, intent)
        self.assertGreaterEqual(
            self.contexts["d-distress"].current_state.emotion.anxiety, 0.7
        )
        from open_llm_vtuber.mental_health.long_term import trend_for_model

        for identity, status in (
            ("d-history-fresh", "usable"),
            ("d-history-stale", "stale"),
        ):
            trend = trend_for_model(self.contexts[identity].long_term_trend)
            self.assertEqual(
                trend["sources"]["system_estimate"]["stress"]["status"], status
            )
        sdk, create = self.sdk()
        await diagnostic.run_case(
            sdk, self.cases["d-help"], self.contexts["d-help"], "baseline"
        )
        context = json.loads(create.call_args.kwargs["messages"][1]["content"])
        self.assertNotIn("expected", context)
        self.assertNotIn("reason", context)
        self.assertEqual(context["recent_states"], [])
        self.assertNotIn("decision_trace", context["current_state"])

    async def test_export_checks_complete_design_raw_outputs_and_request_boundaries(
        self,
    ):
        sdk, _ = self.sdk()
        rows = []
        for case in self.cases.values():
            for variant in diagnostic.VARIANTS:
                row = await diagnostic.run_case(
                    sdk, case, self.contexts[case["id"]], variant
                )
                row["repeat"] = 1
                rows.append(row)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {
                "fixture": self.fixture,
                "contexts": {
                    k: c.model_dump(mode="json") for k, c in self.contexts.items()
                },
                "schedule": [
                    {k: r[k] for k in ("case_id", "variant", "repeat")} for r in rows
                ],
            }
            diagnostic.write_new(root / "manifest.json", manifest)
            report = {
                "status": "complete",
                "manifest_sha256": diagnostic.sha(root / "manifest.json"),
                "rows": rows,
                "metrics": diagnostic.aggregate(rows),
            }
            diagnostic.write_new(root / "report.json", report)
            for i, row in enumerate(rows, 1):
                diagnostic.write_new(root / f"run-{i:03d}.json", row)
            _, _, count = exporter.validate(root)
            self.assertEqual(count, 36)
            original = copy.deepcopy(rows[1])
            mutations = [
                lambda r: r["calls"][0]["request"].update(temperature=1),
                lambda r: r["calls"][0].update(
                    raw_text=r["calls"][0]["raw_text"].replace(
                        "supportive_listening", "close_supportively"
                    )
                ),
                lambda r: r.update(expected=["close_supportively"]),
            ]
            for mutation in mutations:
                changed = copy.deepcopy(original)
                mutation(changed)
                report["rows"][1] = changed
                (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
                (root / "run-002.json").write_text(
                    json.dumps(changed), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    exporter.validate(root)


if __name__ == "__main__":
    unittest.main()
