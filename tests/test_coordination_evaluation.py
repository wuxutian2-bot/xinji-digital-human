import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
import hashlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "coordination_eval", ROOT / "scripts/evaluate_coordination.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
spec_export = importlib.util.spec_from_file_location(
    "coordination_export", ROOT / "scripts/export_coordination_trace.py"
)
exporter = importlib.util.module_from_spec(spec_export)
spec_export.loader.exec_module(exporter)


class CoordinationEvaluationTests(unittest.TestCase):
    def test_schedule_balances_groups_repeats_cases_and_is_reproducible(self):
        cases = evaluation.load_fixtures(
            ROOT / "tests/fixtures/coordination_cases.json"
        )["cases"]
        schedule = evaluation.make_schedule(cases, 3, 42)
        self.assertEqual(schedule, evaluation.make_schedule(cases, 3, 42))
        self.assertEqual(len(schedule), 5 * 3 * len(cases))
        keys = [(s["group"], s["repeat"], s["case_id"]) for s in schedule]
        self.assertEqual(len(keys), len(set(keys)))
        for offset in range(0, len(schedule), 5):
            block = schedule[offset : offset + 5]
            self.assertEqual({s["group"] for s in block}, set(evaluation.GROUPS))
            self.assertEqual(len({s["case_id"] for s in block}), 1)

    def test_holdout_families_and_duplicate_cases_are_rejected(self):
        fixture = evaluation.load_fixtures(
            ROOT / "tests/fixtures/coordination_cases.json"
        )
        for change in (
            lambda f: f["cases"].append(f["cases"][0]),
            lambda f: f["cases"][-1].update(family=f["cases"][0]["family"]),
        ):
            bad = copy.deepcopy(fixture)
            change(bad)
            with TemporaryDirectory() as temp:
                path = Path(temp) / "bad.json"
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    evaluation.load_fixtures(path)

    def test_all_groups_traverse_agent_with_safety_and_correct_ablation(self):
        async def run():
            settings = evaluation.read_settings(
                ROOT / "config_templates/conf.ZH.default.yaml"
            )
            fixture = evaluation.load_fixtures(
                ROOT / "tests/fixtures/coordination_cases.json"
            )
            case = fixture["cases"][0]
            results = {}
            for group in evaluation.GROUPS:
                results[group] = await evaluation.run_case(
                    settings, case, group, fixture["as_of"], None, None, dry_run=True
                )
            for group, rows in results.items():
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(r["pre_safety"] and r["post_safety"] for r in rows))
                self.assertEqual(
                    rows[0]["decision_context"]["user_text"], case["turns"][0]["text"]
                )
                self.assertTrue(all(r["playback_complete"] is None for r in rows))
                self.assertTrue(all(not r["api_calls"] for r in rows))
                if group == "R2":
                    self.assertEqual(rows[0]["intent"]["primary"], "unknown")
                else:
                    self.assertEqual(rows[0]["intent"]["advice_preference"], "declined")
                if group == "R3":
                    self.assertIsNone(rows[0]["trend"])
                    self.assertEqual(rows[0]["decision_context"]["recent_states"], [])
                else:
                    self.assertEqual(
                        rows[0]["trend"]["version"],
                        "rolling_v1" if group == "R4" else "daily_v2",
                    )
            risk = next(c for c in fixture["cases"] if c["category"] == "risk")
            for group in evaluation.GROUPS:
                rows = await evaluation.run_case(
                    settings, risk, group, fixture["as_of"], None, None, dry_run=True
                )
                self.assertEqual(rows[0]["final_strategy"], "crisis_support")
                self.assertEqual(rows[0]["api_calls"], [])
                self.assertEqual(rows[0]["decision_trace"]["source"], "safety_gate")

        asyncio.run(run())

    def test_dry_run_cannot_be_reported_as_model_success(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            evaluation.write_new_json(path, {"dry_run": True})
            with self.assertRaises(FileExistsError):
                evaluation.write_new_json(path, {"dry_run": False})
            self.assertTrue(json.loads(path.read_text())["dry_run"])

    def test_frozen_report_validation_blinding_and_tamper_rejection(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            args = SimpleNamespace(
                config=ROOT / "config_templates/conf.ZH.default.yaml",
                fixtures=ROOT / "tests/fixtures/coordination_cases.json",
                repeats=1,
                order_seed=7,
                dry_run=True,
                output_dir=root / "run",
            )
            self.assertEqual(asyncio.run(evaluation.experiment(args)), 0)
            with self.assertRaises(ValueError):
                exporter.validate_report(args.output_dir)
            report, manifest = exporter.validate_report(
                args.output_dir, allow_dry_run=True
            )
            count = exporter.export(
                args.output_dir, root / "export", allow_dry_run=True
            )
            self.assertEqual(count, 55)
            review = json.loads(
                (root / "export/review-blinded.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(review["items"]), 55)
            self.assertEqual(
                review["source_report_sha256"],
                hashlib.sha256(
                    (args.output_dir / "report.json").read_bytes()
                ).hexdigest(),
            )
            for item in review["items"]:
                self.assertNotIn("source", item)
                self.assertNotIn("group", item)
                self.assertTrue(
                    all(value is None for value in item["ratings"].values())
                )
            with self.assertRaises(FileExistsError):
                exporter.export(args.output_dir, root / "export", allow_dry_run=True)
            report_path = args.output_dir / "report.json"
            for mutate in (
                lambda r: r["runs"].pop(),
                lambda r: r.update(status="partial"),
                lambda r: r.update(dry_run=False),
                lambda r: r["metrics"]["R0"]["ordinary"].update(errors=99),
            ):
                changed = copy.deepcopy(report)
                mutate(changed)
                report_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    exporter.validate_report(args.output_dir, allow_dry_run=True)


if __name__ == "__main__":
    unittest.main()
