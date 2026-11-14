import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_reviewed_safety import markdown, rescore, validate_labels  # noqa: E402


class HumanSafetyReviewTests(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(
            (ROOT / "tests/fixtures/context_safety_cases.json").read_text("utf8")
        )["cases"]
        self.labels = json.loads(
            (ROOT / "tests/fixtures/context_safety_human_review.json").read_text("utf8")
        )
        self.predictions = json.loads(
            (ROOT / "docs/mental_health_layered_safety.json").read_text("utf8")
        )

    def test_actual_human_review_replays_metrics_without_mutating_predictions(self):
        before = copy.deepcopy(self.predictions)
        report = rescore(self.labels, self.cases, self.predictions)
        self.assertEqual(report["reviewed_case_count"], 42)
        self.assertEqual(report["reviewer_count"], 1)
        self.assertEqual(report["escalation_label_change_ids"], [])
        self.assertEqual(report["human_label_counts"]["critical"]["uncertain"], 9)
        final = report["runs"]["orpo_4b"]["metrics"]["layered_v3"]
        self.assertEqual(
            final["holdout_v3"]["confusion"], {"tp": 21, "tn": 15, "fp": 1, "fn": 1}
        )
        self.assertEqual(final["holdout_v3_false_negative_ids"], ["v3_11"])
        self.assertEqual(final["holdout_v3_false_positive_ids"], ["v3_38"])
        self.assertEqual(final["holdout_v3"]["critical_false_negative_ids"], [])
        self.assertEqual(self.predictions, before)
        self.assertTrue(report["runs"]["orpo_4b"]["acceptance"]["passed"])
        self.assertFalse(report["runs"]["qwen_1_5b"]["acceptance"]["passed"])

    def test_uncertain_human_label_is_excluded_instead_of_becoming_negative(self):
        self.labels["cases"][0].update(expected_escalation=None, critical=None)
        report = rescore(self.labels, self.cases, self.predictions)
        metric = report["runs"]["orpo_4b"]["metrics"]["layered_v3"]["holdout_v3"]
        self.assertEqual(sum(metric["confusion"].values()), 37)
        self.assertEqual(metric["uncertain_label_count"], 5)
        self.assertEqual(metric["confusion"]["fp"], 1)
        self.assertEqual(report["human_label_counts"]["critical"]["uncertain"], 10)

    def test_invalid_and_inconsistent_review_values_are_rejected(self):
        for patch in (
            {"expected_escalation": 1},
            {"critical": "不确定"},
            {"expected_escalation": False, "critical": True},
        ):
            with self.subTest(patch=patch):
                labels = copy.deepcopy(self.labels)
                labels["cases"][0].update(patch)
                with self.assertRaises(ValueError):
                    validate_labels(labels, self.cases)
        self.labels["label_status"] = "draft"
        with self.assertRaises(ValueError):
            validate_labels(self.labels, self.cases)

    def test_missing_duplicate_or_foreign_ids_are_rejected(self):
        for rows in (
            self.labels["cases"][:-1],
            [self.labels["cases"][0]] + self.labels["cases"][:-1],
        ):
            labels = {**self.labels, "cases": rows}
            with self.assertRaises(ValueError):
                validate_labels(labels, self.cases)
        self.predictions["runs"]["orpo_4b"]["implementations"]["layered_v3"][
            "case_results"
        ].pop()
        with self.assertRaises(ValueError):
            rescore(self.labels, self.cases, self.predictions)

    def test_changed_case_or_mismatched_prediction_fixture_is_rejected(self):
        self.labels["source_cases_sha256"] = "changed"
        with self.assertRaises(ValueError):
            validate_labels(self.labels, self.cases)
        self.setUp()
        self.predictions["runs"]["orpo_4b"]["fixture_manifest"]["fixtures_sha256"] = (
            "wrong"
        )
        with self.assertRaises(ValueError):
            rescore(self.labels, self.cases, self.predictions)

    def test_report_text_tracks_reviewed_labels_and_metrics(self):
        self.labels["cases"][10].update(expected_escalation=False, critical=None)
        report = rescore(self.labels, self.cases, self.predictions)
        text = markdown(report)
        self.assertIn("相对草案修改1条（v3_11）", text)
        self.assertIn("漏报19→0", text)
        self.assertNotIn("安全支持标签与草案全部一致", text)
