"""Synthetic ratings only; tests never fill the real E1 review forms."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "reviews", ROOT / "scripts/review_coordination.py"
)
reviews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviews)


def bundle():
    items, key, metadata = [], {}, {}
    for index, (group, repeat) in enumerate(
        (("R0", 1), ("R1", 1), ("R0", 2), ("R1", 2)), 1
    ):
        identity = f"item-{index:04d}"
        items.append(
            {
                "id": identity,
                "input": "hello",
                "answer": "Synthetic answer evidence.",
                "conversation_before": [],
                "synthetic_state_history": [],
                "ratings": {field: None for field in reviews.RATING_FIELDS},
                "reviewer_id": None,
            }
        )
        key[identity] = {
            "report_sha256": "report-a",
            "group": group,
            "repeat": repeat,
            "case_id": "case",
            "turn": 1,
        }
        metadata[identity] = {
            "model": "model-a",
            "split": "holdout",
            "category": "intent",
            "error": None,
            "safety_gate": False,
        }
    return {
        "template": {
            "source_report_sha256": ["report-a"],
            "shuffle_seed": 1,
            "items": items,
        },
        "key": key,
        "metadata": metadata,
        "binding": {
            "template_sha256": "template",
            "key_sha256": "key",
            "source_report_sha256": ["report-a"],
        },
    }


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.bundle = bundle()
        self.form = reviews.make_form(self.bundle, "reviewer-a")

    def rated(self, reviewer="reviewer-a", score=3):
        form = reviews.make_form(self.bundle, reviewer)
        for item in form["items"]:
            item["ratings"].update({field: score for field in reviews.SCORE_FIELDS})
            item["ratings"].update({field: False for field in reviews.EVENT_FIELDS})
        return form

    def test_blank_is_pending_and_not_zero_or_agreement(self):
        report = reviews.summarize(self.bundle, [self.form], ["hash-a"])
        self.assertEqual(report["status"], "pending_review")
        self.assertEqual(report["coverage"][0]["complete_items"], 0)
        self.assertIsNone(report["agreement"]["supportiveness"]["exact_agreement"])
        for group in report["summaries"]:
            self.assertIsNone(group["scores"]["supportiveness"]["mean"])
            self.assertEqual(group["events"]["unsupported_diagnosis"]["assessed"], 0)
        for pair in report["paired"]:
            self.assertIsNone(pair["mean_difference"])

    def test_strict_scores_events_and_evidence(self):
        for value in (True, False, 0, 6, 2.5, "3", float("nan")):
            form = copy.deepcopy(self.form)
            form["items"][0]["ratings"]["supportiveness"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                reviews.validate_form(self.bundle, form)
        for value in (1, "false", "true"):
            form = copy.deepcopy(self.form)
            form["items"][0]["ratings"]["unsupported_diagnosis"] = value
            with self.assertRaises(ValueError):
                reviews.validate_form(self.bundle, form)
        form = copy.deepcopy(self.form)
        ratings = form["items"][0]["ratings"]
        ratings["unsupported_diagnosis"] = True
        with self.assertRaises(ValueError):
            reviews.validate_form(self.bundle, form)
        ratings["evidence"] = {
            "unsupported_diagnosis": {"quote": "invented", "note": "synthetic test"}
        }
        with self.assertRaises(ValueError):
            reviews.validate_form(self.bundle, form)
        ratings["evidence"]["unsupported_diagnosis"]["quote"] = "answer evidence"
        reviews.validate_form(self.bundle, form)
        ratings["unsupported_diagnosis"] = False
        with self.assertRaises(ValueError):
            reviews.validate_form(self.bundle, form)

    def test_tampering_missing_duplicate_foreign_and_binding_rejected(self):
        mutations = [
            lambda f: f["items"].pop(),
            lambda f: f["items"].append(f["items"][0]),
            lambda f: f["items"][0].update(id="foreign"),
            lambda f: f["items"][0].update(answer="changed"),
            lambda f: f["items"][0].update(input="changed"),
            lambda f: f.update(template_sha256="wrong"),
            lambda f: f.update(source_report_sha256=["wrong"]),
            lambda f: f["items"][0].update(reviewer_id="another"),
            lambda f: f["items"][0]["ratings"].update(extra=5),
            lambda f: f.update(extra=True),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(self.form)
            mutation(changed)
            with self.assertRaises(ValueError):
                reviews.validate_form(self.bundle, changed)
        reordered = copy.deepcopy(self.form)
        reordered["items"].reverse()
        reviews.validate_form(self.bundle, reordered)

    def test_duplicate_reviewers_and_unsupported_count_rejected(self):
        with self.assertRaises(ValueError):
            reviews.summarize(self.bundle, [self.form, self.form], ["a", "b"])
        with self.assertRaises(ValueError):
            reviews.summarize(self.bundle, [], [])
        with self.assertRaises(ValueError):
            reviews.make_form(self.bundle, "../unsafe")

    def test_single_reviewer_and_partial_coverage_are_explicit(self):
        report = reviews.summarize(self.bundle, [self.rated()], ["a"])
        self.assertEqual(report["status"], "single_reviewer_complete")
        self.assertEqual(report["reviewer_count"], 1)
        self.assertEqual(report["disagreements"], [])
        partial = self.rated()
        partial["items"][0]["ratings"]["intent_fit"] = None
        report = reviews.summarize(self.bundle, [partial], ["a"])
        self.assertEqual(report["status"], "partial_review")
        self.assertEqual(report["coverage"][0]["complete_items"], 3)

    def test_agreement_missingness_and_disputes_do_not_auto_average(self):
        a, b = self.rated(), self.rated("reviewer-b")
        b["items"][0]["ratings"]["supportiveness"] = 5
        b["items"][1]["ratings"]["supportiveness"] = None
        report = reviews.summarize(self.bundle, [a, b], ["a", "b"])
        metric = report["agreement"]["supportiveness"]
        self.assertEqual(metric["both_rated"], 3)
        self.assertEqual(metric["exact_matches"], 2)
        self.assertEqual(metric["one_missing"], 1)
        self.assertEqual(len(report["disagreements"]), 1)
        self.assertIsNone(report["consensus"][0]["ratings"]["supportiveness"])
        self.assertIsNone(report["consensus"][1]["ratings"]["supportiveness"])

    def test_pairs_use_same_reviewer_case_repeat_turn_and_case_equal_weight(self):
        form = self.rated()
        form["items"][1]["ratings"]["supportiveness"] = 5
        form["items"][3]["ratings"]["supportiveness"] = 4
        report = reviews.summarize(self.bundle, [form], ["a"])
        pair = next(
            p
            for p in report["paired"]
            if p["comparison"] == "R1-R0" and p["field"] == "supportiveness"
        )
        self.assertEqual(pair["paired_values"], 2)
        self.assertEqual(pair["mean_difference"], 1.5)
        self.assertEqual(pair["unique_cases"], 1)
        self.assertEqual(pair["case_equal_mean_difference"], 1.5)
        self.assertEqual(pair["delta_histogram"], {"2": 1, "1": 1})

    def test_adjudication_is_bound_to_review_hashes_and_requires_reason(self):
        a, b = self.rated(), self.rated("reviewer-b", 5)
        report = reviews.summarize(self.bundle, [a, b], ["hash-a", "hash-b"])
        adjudication = reviews.adjudication_template(report)
        adjudication["adjudicator_id"] = "adjudicator"
        row = adjudication["items"][0]
        row.update(value=4, reason="Synthetic adjudication justification")
        resolved = reviews.summarize(
            self.bundle, [a, b], ["hash-a", "hash-b"], adjudication
        )
        self.assertEqual(resolved["adjudication"]["resolved"], 1)
        self.assertEqual(resolved["consensus"][0]["ratings"][row["field"]], 4)
        self.assertEqual(a["items"][0]["ratings"][row["field"]], 3)
        for change in (
            lambda x: x.update(review_file_sha256=["bad"]),
            lambda x: x["items"][0].update(reason=None),
            lambda x: x["items"].append(x["items"][0]),
        ):
            bad = copy.deepcopy(adjudication)
            change(bad)
            with self.assertRaises(ValueError):
                reviews.summarize(self.bundle, [a, b], ["hash-a", "hash-b"], bad)

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_no_overwrite(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "file.json"
            for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    reviews.load_json(path)
            reviews.write_new_json(Path(temp) / "new.json", {"value": None})
            with self.assertRaises(FileExistsError):
                reviews.write_new_json(Path(temp) / "new.json", {"value": 5})

    def test_fault_safety_and_error_remain_separate_and_excluded_from_pairs(self):
        for field, value in (
            ("category", "fault"),
            ("safety_gate", True),
            ("error", "synthetic error"),
        ):
            data = copy.deepcopy(self.bundle)
            data["metadata"]["item-0002"][field] = value
            report = reviews.summarize(data, [self.rated()], ["a"])
            pair = next(p for p in report["paired"] if p["field"] == "supportiveness")
            self.assertEqual(pair["paired_values"], 1)
            self.assertEqual(pair["pairs"][0]["repeat"], 2)
            self.assertEqual(sum(s["items"] for s in report["summaries"]), 4)
            self.assertEqual(len(report["summaries"]), 3)

    def test_event_adjudication_requires_quote_and_preserves_original_scores(self):
        a, b = self.rated(), self.rated("reviewer-b")
        evidence = {
            "quote": "Synthetic answer",
            "note": "Synthetic event justification",
        }
        a["items"][0]["ratings"].update(
            unsupported_diagnosis=True, evidence={"unsupported_diagnosis": evidence}
        )
        report = reviews.summarize(self.bundle, [a, b], ["a", "b"])
        self.assertEqual(report["status"], "pending_adjudication")
        adjudication = reviews.adjudication_template(report)
        adjudication["adjudicator_id"] = "adjudicator"
        adjudication["items"][0].update(value=True, reason="Synthetic reason")
        with self.assertRaises(ValueError):
            reviews.summarize(self.bundle, [a, b], ["a", "b"], adjudication)
        adjudication["items"][0]["evidence"] = evidence
        resolved = reviews.summarize(self.bundle, [a, b], ["a", "b"], adjudication)
        self.assertEqual(resolved["status"], "two_reviewers_complete")
        self.assertEqual(resolved["adjudication"]["pending"], 0)
        self.assertIs(
            resolved["consensus"][0]["ratings"]["unsupported_diagnosis"], True
        )
        self.assertIs(b["items"][0]["ratings"]["unsupported_diagnosis"], False)

    def test_cli_prepares_and_exports_without_filling_scores(self):
        with (
            TemporaryDirectory() as temp,
            patch.object(reviews, "load_bundle", return_value=self.bundle),
        ):
            root = Path(temp)
            common = [
                "--bundle",
                "bundle",
                "--experiment",
                "orpo",
                "--experiment",
                "sft",
            ]
            reviews.main(
                common
                + [
                    "prepare",
                    "--reviewer-ids",
                    "reviewer-a",
                    "reviewer-b",
                    "--output-dir",
                    str(root / "forms"),
                ]
            )
            reviews.main(
                common
                + [
                    "summarize",
                    "--reviews",
                    str(root / "forms/reviewer-a.json"),
                    str(root / "forms/reviewer-b.json"),
                    "--output-dir",
                    str(root / "report"),
                ]
            )
            report = reviews.load_json(root / "report/summary.json")
            self.assertEqual(report["status"], "pending_review")
            self.assertEqual(report["active_reviewers"], 0)
            self.assertEqual(report["agreement"]["coherence"]["both_missing"], 4)
            with self.assertRaises(FileExistsError):
                reviews.prepare(self.bundle, ["reviewer-a"], root / "forms")
            for aliases in (["reviewer-a", "Reviewer-A"], ["CON"]):
                with self.assertRaises(ValueError):
                    reviews.prepare(self.bundle, aliases, root / "invalid")
                self.assertFalse((root / "invalid").exists())

    def test_bundle_reconstructs_blinding_and_rejects_rebound_wrong_answer(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            export = root / "bundle"
            export.mkdir()
            report = {
                "runs": [
                    {
                        "group": "R0",
                        "repeat": 1,
                        "case_id": "case",
                        "split": "holdout",
                        "category": "intent",
                        "turns": [
                            {
                                "turn": 1,
                                "input": "hello",
                                "response": "Synthetic answer",
                                "human_ratings": {
                                    field: None for field in reviews.RATING_FIELDS
                                },
                                "error": None,
                                "pre_safety": {"action": "allow"},
                            }
                        ],
                    }
                ]
            }
            manifest = {
                "configuration": {"dialogue_model": "model-a"},
                "fixtures": {"cases": [{"id": "case"}]},
            }
            experiment = root / "experiment"
            experiment.mkdir()
            reviews.write_new_json(experiment / "report.json", report)
            report_hash = reviews.sha(experiment / "report.json")
            template, key = reviews.combined_review(
                [report], [manifest], [report_hash], 1
            )
            reviews.write_new_json(export / "review-blinded-combined.json", template)
            reviews.write_new_json(export / "review-key.json", key)
            with patch.object(
                reviews, "validate_report", return_value=(report, manifest)
            ):
                loaded = reviews.load_bundle(export, [experiment])
                self.assertEqual(len(loaded["template"]["items"]), 1)
                template["items"][0]["answer"] = "tampered answer"
                (export / "review-blinded-combined.json").write_text(
                    json.dumps(template)
                )
                with self.assertRaises(ValueError):
                    reviews.load_bundle(export, [experiment])


if __name__ == "__main__":
    unittest.main()
