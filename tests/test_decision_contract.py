import copy
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_decision_contract as experiment  # noqa: E402
from decision_contract import CONTRACT, transform  # noqa: E402
from validate_decision_contract import validate, screening_gate  # noqa: E402
from open_llm_vtuber.mental_health.schemas import DecisionResult  # noqa: E402


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = json.loads(
            (ROOT / "tests/fixtures/decision_diagnostic_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.case = self.fixture["cases"][1]
        self.context = await experiment.diagnostic.build_context(
            self.case, datetime.fromisoformat(self.fixture["now"])
        )

    def sdk(self):
        create = AsyncMock(
            return_value=SimpleNamespace(
                model=experiment.diagnostic.MODEL,
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=DecisionResult().model_dump_json()
                        ),
                        finish_reason="stop",
                    )
                ],
            )
        )
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ), create

    async def test_contract_records_exact_wire_and_changes_only_prompt_against_both(
        self,
    ):
        sdk, create = self.sdk()
        baseline = await experiment.run_case(sdk, self.case, self.context, "baseline")
        request = baseline["calls"][0]["request"]
        original = copy.deepcopy(request)
        both = transform(request, "both")
        contract = transform(request, "contract_v1")
        self.assertTrue(contract["messages"][0]["content"].startswith(CONTRACT))
        copied = copy.deepcopy(contract)
        copied["messages"][0] = both["messages"][0]
        self.assertEqual(copied, both)
        self.assertEqual(request, original)
        row = await experiment.run_case(sdk, self.case, self.context, "contract_v1")
        self.assertEqual(row["calls"][0]["request"], create.call_args.kwargs)
        self.assertEqual(row["variant"], "contract_v1")
        self.assertFalse(row["proposed_match"])
        self.assertTrue(row["final_match"])
        self.assertNotIn("expected", json.loads(contract["messages"][1]["content"]))

    async def test_safety_zero_calls_and_no_unsupported_variant(self):
        sdk, create = self.sdk()
        case = self.fixture["cases"][-1]
        context = await experiment.diagnostic.build_context(
            case, datetime.fromisoformat(self.fixture["now"])
        )
        for variant in experiment.VARIANTS:
            row = await experiment.run_case(sdk, case, context, variant)
            self.assertEqual(row["source"], "safety_gate")
            self.assertEqual(row["calls"], [])
        create.assert_not_awaited()
        with self.assertRaises(ValueError):
            transform({}, "unknown")

    async def test_frozen_candidate_and_single_holdout_enforced_before_calls(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            freeze = root / "freeze.json"
            experiment.freeze(freeze)
            with self.assertRaises(FileExistsError):
                experiment.freeze(freeze)
            fixture = copy.deepcopy(self.fixture)
            fixture.update(
                split="holdout",
                candidate_freeze_sha256=experiment.diagnostic.sha(freeze),
            )
            experiment.diagnostic.write_new(root / "fixture.json", fixture)
            args = SimpleNamespace(
                fixtures=root / "fixture.json",
                split="holdout",
                freeze=freeze,
                output=root / "output",
                repeats=1,
            )
            with (
                patch.object(experiment, "sources", return_value={"changed": "source"}),
                self.assertRaises(ValueError),
            ):
                await experiment.evaluate(args)
            self.assertFalse(args.output.exists())
            experiment.diagnostic.write_new(
                freeze.with_suffix(".holdout-started.json"), {}
            )
            with self.assertRaises(ValueError):
                await experiment.evaluate(args)
            self.assertFalse(args.output.exists())

    async def test_invalid_fixture_rejected(self):
        experiment.validate_fixture(self.fixture)
        for mutation in (
            lambda f: f["cases"].append(f["cases"][0]),
            lambda f: f["cases"][0].update(history="invented"),
            lambda f: f["cases"][0].update(expected=["diagnosis"]),
        ):
            bad = copy.deepcopy(self.fixture)
            mutation(bad)
            with self.assertRaises(ValueError):
                experiment.validate_fixture(bad)

    async def test_artifact_audit_rejects_tampered_prompt_raw_result_and_counts(self):
        sdk, _ = self.sdk()
        rows = []
        for variant in experiment.VARIANTS:
            row = await experiment.run_case(sdk, self.case, self.context, variant)
            row["repeat"] = 1
            rows.append(row)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {
                "split": "development",
                "fixture": {"cases": [self.case]},
                "contexts": {self.case["id"]: self.context.model_dump(mode="json")},
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
            }

            def save(value):
                (root / "report.json").write_text(json.dumps(value), encoding="utf-8")
                for i, row in enumerate(value["rows"], 1):
                    (root / f"run-{i:03d}.json").write_text(
                        json.dumps(row), encoding="utf-8"
                    )

            save(report)
            self.assertEqual(validate(root)["request_boundary_checks"], 3)
            changes = [
                lambda r: r["rows"][2]["calls"][0]["request"]["messages"][0].update(
                    content="other prompt"
                ),
                lambda r: r["rows"][2]["calls"][0].update(
                    raw_text=DecisionResult(
                        strategy={"primary": "close_supportively"}
                    ).model_dump_json()
                ),
                lambda r: r["metrics"]["contract_v1"].update(proposed_matches=999),
                lambda r: r["rows"].pop(),
            ]
            for change in changes:
                changed = copy.deepcopy(report)
                change(changed)
                save(changed)
                with self.assertRaises(ValueError):
                    validate(root)

    async def test_screening_gate_cannot_hide_fallbacks_critical_failures_or_safety_calls(
        self,
    ):
        fixture = {
            "acceptance": {
                "candidate_min_raw_match_rate": 0.9,
                "candidate_min_valid_rate": 0.95,
                "critical_case_ids": ["normal"],
            },
            "cases": [
                {"id": "normal", "expected": ["supportive_listening"]},
                {"id": "risk", "expected": []},
            ],
        }
        report = {
            "split": "holdout",
            "rows": [
                {
                    "case_id": "normal",
                    "repeat": 1,
                    "variant": "contract_v1",
                    "source": "model",
                    "proposed_match": True,
                    "calls": [{}],
                },
                {
                    "case_id": "risk",
                    "repeat": 1,
                    "variant": "baseline",
                    "source": "safety_gate",
                    "proposed_match": None,
                    "calls": [],
                },
            ],
        }
        self.assertEqual(screening_gate(report, fixture)["status"], "passed")
        bad = copy.deepcopy(report)
        bad["rows"][0].update(source="fallback", proposed_match=None)
        gate = screening_gate(bad, fixture)
        self.assertEqual(gate["scheduled_normal_rows"], 1)
        self.assertEqual(gate["valid_rate"], 0)
        self.assertEqual(gate["raw_match_rate"], 0)
        self.assertEqual(len(gate["critical_failures"]), 1)
        bad = copy.deepcopy(report)
        bad["rows"][1]["calls"] = [{}]
        self.assertEqual(screening_gate(bad, fixture)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
