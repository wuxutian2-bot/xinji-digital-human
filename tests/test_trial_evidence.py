import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "trial_evidence", Path(__file__).resolve().parents[1] / "scripts/trial_evidence.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TrialEvidenceTests(unittest.TestCase):
    def test_blank_does_not_invent_visits_or_ratings(self):
        report = module.summarize(
            module.Study(version="test", participants=[module.Participant(id="P01")])
        )
        self.assertEqual(report["visited"], 0)
        self.assertIsNone(report["ratings"]["被理解感"]["mean"])

    def test_missing_negative_and_assisted_remain_visible(self):
        person = module.Participant(
            id="P01",
            consent=True,
            adult_confirmed=True,
            visited=True,
            ratings={"被理解感": 1, "偏好被尊重": 5, "记忆控制感": None},
        )
        person.tasks["倾诉"].result = "assisted"
        report = module.summarize(module.Study(version="test", participants=[person]))
        self.assertEqual(report["tasks"]["倾诉"]["assisted"], 1)
        self.assertEqual(report["ratings"]["记忆控制感"]["missing"], 1)
        self.assertEqual(report["ratings"]["被理解感"]["low_1_or_2"], 1)

    def test_rejects_synthetic_duplicates_unconsented_and_false_return(self):
        for values in [
            dict(synthetic=True, participants=[]),
            dict(participants=[{"id": "P01"}, {"id": "P01"}]),
            dict(participants=[{"id": "P01", "visited": True}]),
            dict(participants=[{"id": "P01", "returned": True}]),
        ]:
            with self.assertRaises(ValueError):
                module.Study(version="test", **values)


if __name__ == "__main__":
    unittest.main()
