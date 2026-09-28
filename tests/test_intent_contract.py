import copy
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_intent_contract as experiment  # noqa: E402
from decision_intent_contract import transform, CONTRACT_V2  # noqa: E402
from validate_intent_contract import validate  # noqa: E402
from open_llm_vtuber.mental_health.schemas import DecisionResult  # noqa: E402


class IntentContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = json.loads(
            (ROOT / "tests/fixtures/decision_intent_development.json").read_text(
                encoding="utf-8"
            )
        )
        self.cases = {c["id"]: c for c in self.fixture["cases"]}
        self.contexts = {
            k: await experiment.diagnostic.build_context(
                c, datetime.fromisoformat(self.fixture["now"])
            )
            for k, c in self.cases.items()
        }

    def sdk(self, strategy="supportive_listening", finish="stop"):
        create = AsyncMock(
            return_value=SimpleNamespace(
                model=experiment.diagnostic.MODEL,
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=DecisionResult(
                                strategy={"primary": strategy}
                            ).model_dump_json()
                        ),
                        finish_reason=finish,
                    )
                ],
            )
        )
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ), create

    async def test_only_system_prompt_changes_and_effective_request_is_captured(self):
        sdk, create = self.sdk("collaborative_problem_solving")
        case, context = self.cases["c-choice"], self.contexts["c-choice"]
        original = context.model_dump()
        v1 = await experiment.run_case(sdk, case, context, "contract_v1")
        v2 = await experiment.run_case(sdk, case, context, "contract_v2")
        a, b = v1["calls"][0]["request"], v2["calls"][0]["request"]
        self.assertEqual(b, create.call_args.kwargs)
        self.assertEqual(transform(a, "contract_v2"), b)
        self.assertTrue(b["messages"][0]["content"].startswith(CONTRACT_V2))
        unchanged = copy.deepcopy(b)
        unchanged["messages"][0] = a["messages"][0]
        self.assertEqual(unchanged, a)
        self.assertEqual(original, context.model_dump())
        self.assertNotIn("expected", json.loads(b["messages"][1]["content"]))
        self.assertEqual(v2["local_intent"]["primary"], "unknown")
        self.assertEqual(
            v2["rule_final"]["strategy"]["primary"], "supportive_listening"
        )
        self.assertTrue(v2["proposed_match"])

    async def test_safety_bypasses_and_failure_does_not_inflate_match(self):
        sdk, create = self.sdk()
        for variant in experiment.VARIANTS:
            row = await experiment.run_case(
                sdk, self.cases["c-risk"], self.contexts["c-risk"], variant
            )
            self.assertEqual(row["source"], "safety_gate")
            self.assertIsNone(row["rule_final"])
            self.assertEqual(row["calls"], [])
        create.assert_not_awaited()
        sdk, _ = self.sdk("collaborative_problem_solving", finish="length")
        row = await experiment.run_case(
            sdk, self.cases["c-choice"], self.contexts["c-choice"], "contract_v2"
        )
        metrics = experiment.aggregate([row])["contract_v2"]
        self.assertEqual(metrics["scheduled_normal"], 1)
        self.assertEqual(metrics["valid"], 0)
        self.assertEqual(metrics["unknown_proposed_matches"], 0)

    async def test_holdout_requires_unmodified_candidate_three_repeats_and_single_exposure(
        self,
    ):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "freeze.json"
            experiment.freeze(path)
            args = SimpleNamespace(split="holdout", repeats=3, freeze=path)
            fixture = {
                "split": "holdout",
                "candidate_freeze_sha256": experiment.diagnostic.sha(path),
            }
            marker = experiment.check_holdout(args, fixture, experiment.sources())
            with self.assertRaises(ValueError):
                experiment.check_holdout(args, fixture, {"changed": "source"})
            args.repeats = 1
            with self.assertRaises(ValueError):
                experiment.check_holdout(args, fixture, experiment.sources())
            args.repeats = 3
            experiment.diagnostic.write_new(marker, {})
            with self.assertRaises(ValueError):
                experiment.check_holdout(args, fixture, experiment.sources())
            args.split = "development"
            with self.assertRaises(ValueError):
                experiment.check_holdout(args, fixture, experiment.sources())

    async def test_gate_keeps_critical_failures_even_when_rate_is_high(self):
        fixture = {
            "acceptance": {
                "min_raw_match_rate": 0.9,
                "min_valid_rate": 0.95,
                "critical_case_ids": ["critical"],
            }
        }
        report = {
            "metrics": {
                "contract_v2": {
                    "scheduled_normal": 10,
                    "proposed_matches": 9,
                    "valid": 10,
                }
            },
            "rows": [
                {
                    "variant": "contract_v2",
                    "case_id": "critical",
                    "repeat": 1,
                    "source": "model",
                    "proposed_match": False,
                    "expected": ["supportive_listening"],
                    "calls": [{}],
                }
            ],
        }
        gate = experiment.screening_gate(report, fixture)
        self.assertEqual(gate["raw_match_rate"], 0.9)
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(len(gate["critical_failures"]), 1)

    async def test_audit_recomputes_rules_and_rejects_raw_request_or_metric_tampering(
        self,
    ):
        sdk, _ = self.sdk("collaborative_problem_solving")
        case, context = self.cases["c-choice"], self.contexts["c-choice"]
        rows = []
        for variant in experiment.VARIANTS:
            row = await experiment.run_case(sdk, case, context, variant)
            row["repeat"] = 1
            rows.append(row)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {
                "split": "development",
                "fixture": {"cases": [case]},
                "contexts": {case["id"]: context.model_dump(mode="json")},
                "schedule": [
                    {k: r[k] for k in ("case_id", "variant", "repeat")} for r in rows
                ],
            }
            experiment.diagnostic.write_new(root / "manifest.json", manifest)
            report = {
                "status": "complete",
                "split": "development",
                "manifest_sha256": experiment.diagnostic.sha(root / "manifest.json"),
                "rows": rows,
                "metrics": experiment.aggregate(rows),
                "screening_gate": None,
            }

            def save(value):
                (root / "report.json").write_text(json.dumps(value), encoding="utf-8")
                for i, row in enumerate(value["rows"], 1):
                    (root / f"run-{i:03d}.json").write_text(
                        json.dumps(row), encoding="utf-8"
                    )

            save(report)
            self.assertEqual((await validate(root))["request_boundary_checks"], 2)
            mutations = [
                lambda r: r["rows"][1]["rule_final"]["strategy"].update(
                    primary="collaborative_problem_solving"
                ),
                lambda r: r["rows"][1]["local_intent"].update(
                    primary="seeking_practical_help"
                ),
                lambda r: r["rows"][1]["calls"][0]["request"].update(temperature=1),
                lambda r: r["rows"][1]["calls"][0].update(
                    raw_text=DecisionResult().model_dump_json()
                ),
                lambda r: r["metrics"]["contract_v2"].update(proposed_matches=10),
                lambda r: r["rows"].pop(),
            ]
            for mutation in mutations:
                bad = copy.deepcopy(report)
                mutation(bad)
                save(bad)
                with self.assertRaises(ValueError):
                    await validate(root)


if __name__ == "__main__":
    unittest.main()
