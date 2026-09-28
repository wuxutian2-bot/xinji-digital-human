"""C1 fixture and baseline metric contract; semantic signal parser is pending C2."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_context_safety import metrics, validate_cases  # noqa: E402


class ContextBaselineTests(unittest.TestCase):
    def test_fixture_has_disjoint_families_and_critical_labels(self):
        cases = json.loads(
            (ROOT / "tests/fixtures/context_safety_cases.json").read_text(
                encoding="utf-8"
            )
        )["cases"]
        validate_cases(cases)
        self.assertEqual(len(cases), 80)
        self.assertEqual(sum(c["split"] == "holdout" for c in cases), 40)
        self.assertTrue(any(c.get("prior") for c in cases))
        self.assertTrue(any(c["expected_escalation"] is None for c in cases))
        broken = copy.deepcopy(cases)
        broken[-1]["family"] = broken[0]["family"]
        with self.assertRaises(ValueError):
            validate_cases(broken)

    def test_unknown_labels_are_not_true_negatives_or_passes(self):
        result = metrics(
            [
                {"id": "ambiguous", "expected_escalation": None, "escalated": False},
                {
                    "id": "miss",
                    "expected_escalation": True,
                    "escalated": False,
                    "critical": True,
                },
                {"id": "false_alarm", "expected_escalation": False, "escalated": True},
            ]
        )
        self.assertEqual(result["confusion"], {"tp": 0, "tn": 0, "fp": 1, "fn": 1})
        self.assertEqual(result["critical_false_negative_ids"], ["miss"])
        self.assertEqual(result["uncertain_label_count"], 1)
