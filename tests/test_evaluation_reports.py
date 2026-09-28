"""Prevent misleading comparisons when saved evaluation inputs differ."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "compare_reports", ROOT / "scripts/compare_mental_health.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvaluationReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixtures = self.root / "fixtures.json"
        self.fixtures.write_text(
            json.dumps({"cases": [{"id": "one", "text": "Synthetic prompt"}]}),
            encoding="utf-8",
        )
        self.report = {
            "created_at": "2026-09-22T00:00:00Z",
            "provenance": {
                "fixtures_sha256": hashlib.sha256(
                    self.fixtures.read_bytes()
                ).hexdigest(),
                "source_sha256": {"a.py": "same"},
            },
            "persona_sha256": "same",
            "configuration": {
                "dialogue": "model",
                "model": "test",
                "memory": True,
                "expression": True,
                "safety": "always_on",
                "temperature": 0,
                "max_tokens": 384,
            },
            "metrics": {
                "errors": 0,
                "latency_mean_seconds": 1,
                "safety_confusion": {"tp": 0, "fp": 0, "tn": 1, "fn": 0},
            },
            "cases": [
                {
                    "id": "one",
                    "dialogue_calls": 1,
                    "completions": [{"finish_reason": "length"}],
                    "responses": ["Synthetic answer"],
                }
            ],
        }

    def write(self, name, report):
        path = self.root / name
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_different_fixture_or_missing_case_cannot_produce_comparison(self):
        for mutate in (
            lambda r: r["provenance"].update(fixtures_sha256="wrong"),
            lambda r: r.update(cases=[]),
            lambda r: r["cases"].append(r["cases"][0]),
        ):
            with self.subTest(mutate=mutate):
                report = copy.deepcopy(self.report)
                mutate(report)
                output = self.root / "invalid.md"
                with self.assertRaises(ValueError):
                    module.compare(
                        [self.write("report.json", report)], output, self.fixtures
                    )
                self.assertFalse(output.exists())

    def test_disabled_safety_is_not_accepted_as_supported_ablation(self):
        self.report["configuration"]["safety"] = "disabled"
        with self.assertRaises(ValueError):
            module.compare(
                [self.write("report.json", self.report)],
                self.root / "out.md",
                self.fixtures,
            )

    def test_report_discloses_truncation_prompt_and_generation_mismatch(self):
        other = copy.deepcopy(self.report)
        other["configuration"]["max_tokens"] = 100
        output = self.root / "out.md"
        module.compare(
            [self.write("first.json", self.report), self.write("second.json", other)],
            output,
            self.fixtures,
        )
        text = output.read_text(encoding="utf-8")
        for expected in (
            "Synthetic prompt",
            "Synthetic answer",
            "长度截断 1 次",
            "生成参数一致：否",
            "支持性：待评",
        ):
            self.assertIn(expected, text)

    def test_legacy_missing_metadata_is_unknown_not_success(self):
        self.report.pop("persona_sha256")
        self.report["cases"][0].pop("completions")
        output = self.root / "out.md"
        module.compare([self.write("legacy.json", self.report)], output, self.fixtures)
        text = output.read_text(encoding="utf-8")
        self.assertIn("未记录，无法核对", text)
        self.assertIn("未记录完成原因", text)


if __name__ == "__main__":
    unittest.main()
