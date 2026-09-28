import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "model_comparison", ROOT / "scripts/compare_coordination_models.py"
)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class CoordinationComparisonTests(unittest.TestCase):
    def test_combined_review_mixes_models_and_binds_every_blank_rating(self):
        manifest = {"fixtures": {"cases": [{"id": "one", "history": []}]}}
        report = {
            "runs": [
                {
                    "group": "R0",
                    "repeat": 1,
                    "case_id": "one",
                    "turns": [
                        {
                            "turn": 1,
                            "input": "hello",
                            "response": "reply",
                            "human_ratings": {
                                "supportiveness": None,
                                "intent_fit": None,
                            },
                        }
                    ],
                }
            ]
        }
        review, key = comparison.combined_review(
            [report, report], [manifest, manifest], ["hash-a", "hash-b"], 7
        )
        self.assertEqual(len(review["items"]), 2)
        self.assertEqual(
            {row["report_sha256"] for row in key["items"].values()},
            {"hash-a", "hash-b"},
        )
        self.assertEqual({item["id"] for item in review["items"]}, set(key["items"]))
        for item in review["items"]:
            self.assertNotIn("group", item)
            self.assertNotIn("_source", item)
            self.assertTrue(all(value is None for value in item["ratings"].values()))
        self.assertEqual(
            (review, key),
            comparison.combined_review(
                [report, report], [manifest, manifest], ["hash-a", "hash-b"], 7
            ),
        )

    def test_only_dialogue_model_and_adapter_may_differ(self):
        left = {
            "persona_sha256": "p",
            "groups": "groups",
            "repeats": 3,
            "order_seed": 1,
            "schedule": [1],
            "fixtures": {"x": 1},
            "as_of": "fixed",
            "provenance": {"source_sha256": {"a": "s"}, "fixtures_sha256": "f"},
            "configuration": {
                "dialogue_model": "orpo",
                "temperature": 0,
                "safety": "always_on",
            },
            "model_artifacts": {
                "base_weights": "b",
                "decision_weights": "d",
                "adapter_weights": "orpo",
            },
        }
        right = copy.deepcopy(left)
        right["configuration"]["dialogue_model"] = "sft"
        right["model_artifacts"]["adapter_weights"] = "sft"
        comparison.validate_pair(left, right)
        for mutate in (
            lambda r: r.update(repeats=2),
            lambda r: r.update(as_of="other"),
            lambda r: r["provenance"].update(fixtures_sha256="bad"),
            lambda r: r["configuration"].update(temperature=1),
            lambda r: r["model_artifacts"].update(decision_weights="other"),
            lambda r: r["model_artifacts"].update(base_weights="other"),
            lambda r: r["model_artifacts"].update(base_extra="extra"),
            lambda r: r["configuration"].update(dialogue_model="orpo"),
        ):
            changed = copy.deepcopy(right)
            mutate(changed)
            with self.assertRaises(ValueError):
                comparison.validate_pair(left, changed)


if __name__ == "__main__":
    unittest.main()
