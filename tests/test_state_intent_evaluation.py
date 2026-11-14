import csv
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_llm_vtuber.mental_health.schemas import PsychologicalState

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "state_intent_evaluation", ROOT / "scripts/evaluate_state_intent.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class StateIntentEvaluationTests(unittest.TestCase):
    def test_two_reviewers_use_one_shared_prediction_batch(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = root / "tests/fixtures"
            fixtures.mkdir(parents=True)
            cases = [
                dict(
                    id=split,
                    text="我压力很大",
                    stress=0.2,
                    anxiety=None,
                    low_mood=None,
                    intent="venting",
                    advice_preference="unspecified",
                    split=split,
                )
                for split in ("dev", "holdout")
            ]
            (fixtures / "state_intent_eval.json").write_text(json.dumps(cases), "utf8")
            paths = []
            for who, score in (("a", 0.2), ("b", 0.8)):
                path = root / (who + ".csv")
                with path.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=[
                            "id",
                            "text",
                            *evaluation.DIMS,
                            "intent",
                            "advice_preference",
                        ],
                    )
                    writer.writeheader()
                    for case in cases:
                        writer.writerow(
                            {
                                k: (
                                    score
                                    if k == "stress"
                                    else "null"
                                    if case[k] is None
                                    else case[k]
                                )
                                for k in writer.fieldnames
                            }
                        )
                paths.append(path)
            engine = SimpleNamespace(
                estimate=AsyncMock(
                    side_effect=evaluation.ContextStateEstimator().estimate
                ),
                aclose=AsyncMock(),
            )
            args = SimpleNamespace(
                adjudicated=paths[0],
                reference=paths[1],
                base_url="http://localhost",
                model="fake",
                key="unused",
                timeout=1,
                db=None,
                output=root / "report.md",
            )
            with (
                patch.object(evaluation, "ROOT", root),
                patch.object(
                    evaluation, "LLMStateIntentEstimator", return_value=engine
                ),
            ):
                asyncio.run(evaluation.evaluate(args))
            result = json.loads((root / "report.json").read_text("utf8"))
            self.assertEqual(result["labels"], "independent_reviewers")
            self.assertEqual(engine.estimate.await_count, 2)
            first = result["metrics"]["holdout"]["llm"]["dimensions"]["stress"]
            second = result["reference_metrics"]["holdout"]["llm"]["dimensions"][
                "stress"
            ]
            self.assertEqual(first["observed_f1"], second["observed_f1"])
            self.assertNotEqual(first["mae"], second["mae"])
            self.assertEqual(len(result["predictions"]["holdout"]["llm"]), 1)

    def test_unknown_and_zero_have_different_observation_counts(self):
        truth = dict(
            stress=0.0,
            anxiety=None,
            low_mood=0.5,
            intent="venting",
            advice_preference="declined",
        )
        prediction = dict(truth, stress=None, low_mood=0.7)
        result = evaluation.metrics([(truth, prediction)])
        self.assertEqual(result["dimensions"]["stress"]["observed_f1"], 0)
        self.assertIsNone(result["dimensions"]["stress"]["mae"])
        self.assertAlmostEqual(result["dimensions"]["low_mood"]["mae"], 0.2)
        self.assertEqual(result["intent_accuracy"], 1)

    def test_calibration_matches_same_user_and_day(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "memory.db"
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE states (user_id TEXT,timestamp REAL,payload TEXT)"
                )
                for day in range(3):
                    for source, score in (
                        ("llm_v1", 0.2 + day * 0.2),
                        ("user_report", 0.1 + day * 0.2),
                    ):
                        state = PsychologicalState(
                            estimator_source=source,
                            emotion={"stress": score},
                            observed_dimensions=["stress"],
                        )
                        db.execute(
                            "INSERT INTO states VALUES (?,?,?)",
                            ("a", 1700000000 + day * 86400, state.model_dump_json()),
                        )
                state = PsychologicalState(
                    estimator_source="user_report",
                    emotion={"anxiety": 0.8},
                    observed_dimensions=["anxiety"],
                )
                db.execute(
                    "INSERT INTO states VALUES (?,?,?)",
                    ("b", 1700000000, state.model_dump_json()),
                )
            db.close()
            result = evaluation.calibrate(path)
            self.assertEqual(result["stress"]["paired_days"], 3)
            self.assertAlmostEqual(result["stress"]["mean_bias"], 0.1)
            self.assertAlmostEqual(result["stress"]["spearman"], 1)
            self.assertEqual(result["anxiety"]["paired_days"], 0)
            self.assertIsNone(result["anxiety"]["pearson"])

    def test_incomplete_annotations_are_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "labels.csv"
            case = dict(
                id="one", text="虚构原文", stress=None, anxiety=None, low_mood=None
            )
            for value in ("", "nan", "1.1"):
                with path.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=[
                            "id",
                            "text",
                            *evaluation.DIMS,
                            "intent",
                            "advice_preference",
                        ],
                    )
                    writer.writeheader()
                    writer.writerow(
                        dict(
                            case,
                            stress=value,
                            anxiety="null",
                            low_mood="null",
                            intent="venting",
                            advice_preference="unspecified",
                        )
                    )
                with self.assertRaises(ValueError):
                    evaluation.load_truth([case.copy()], path)
