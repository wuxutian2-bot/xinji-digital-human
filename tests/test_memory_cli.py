import asyncio
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_llm_vtuber.mental_health.schemas import PsychologicalState
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService

spec = importlib.util.spec_from_file_location(
    "memory_cli",
    Path(__file__).resolve().parents[1] / "scripts/manage_psychological_memory.py",
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class MemoryCliTests(unittest.TestCase):
    def test_trend_uses_full_window_user_isolation_and_unknown_dimensions(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "states.db"
            now = datetime(2026, 9, 22, tzinfo=timezone.utc)
            owner = SqlitePsychologicalMemoryService(str(db), "owner", recent_limit=1)
            other = SqlitePsychologicalMemoryService(str(db), "other")
            for day in (1, 2, 3, 8, 9, 10):
                asyncio.run(
                    owner.append(
                        "history-" + str(day),
                        PsychologicalState(
                            timestamp=now - timedelta(days=day),
                            estimator_source="keyword_v1",
                            emotion={"stress": 0.8 if day < 7 else 0.2},
                            observed_dimensions=["stress"],
                            topics=["work"],
                        ),
                    )
                )
            asyncio.run(
                other.append(
                    "private",
                    PsychologicalState(
                        timestamp=now,
                        emotion={"anxiety": 1},
                        observed_dimensions=["anxiety"],
                    ),
                )
            )
            output = Path(temp) / "trend.json"
            args = [
                "--database",
                str(db),
                "--user-id",
                "owner",
                "trend",
                "--at",
                "2026-09-22T08:00:00+08:00",
                "--output",
                str(output),
            ]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["as_of"], now.isoformat())
            self.assertEqual(report["trend"]["sample_count"], 3)
            self.assertEqual(report["trend"]["changes"]["stress"], 0.6)
            self.assertIsNone(report["trend"]["means"]["anxiety"])
            self.assertEqual(report["trend"]["recurring_topics"], ["work"])
            before = output.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(args)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(len(owner.list_records()), 6)

    def test_missing_database_and_naive_timestamp_are_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "missing.db"
            for extra in ([], ["--at", "2026-09-22T08:00:00"]):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    cli.main(
                        ["--database", str(path), "--user-id", "owner", "trend", *extra]
                    )
            self.assertFalse(path.exists())

    def test_empty_profile_reports_unknown_not_zero(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "state.db"
            SqlitePsychologicalMemoryService(str(db), "owner")
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(["--database", str(db), "--user-id", "owner", "trend"])
            trend = json.loads(output.getvalue())["trend"]
            self.assertTrue(trend["insufficient_data"])
            self.assertTrue(all(value is None for value in trend["means"].values()))

    def test_self_report_is_explicit_and_trend_versions_are_selectable(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "state.db"
            report_path = Path(temp) / "report.json"
            report_path.write_text(
                json.dumps(
                    {"timestamp": "2020-01-03T12:00:00+08:00", "emotion": {"stress": 0}}
                ),
                encoding="utf-8",
            )
            base = ["--database", str(db), "--user-id", "owner"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.main(
                        [
                            *base,
                            "self-report",
                            "--input",
                            str(report_path),
                            "--history-scope",
                            "manual",
                        ]
                    ),
                    0,
                )
            owner = SqlitePsychologicalMemoryService(str(db), "owner")
            saved = owner.list_records()[0]
            self.assertEqual(saved["history_scope"], "manual")
            self.assertEqual(saved["state"]["estimator_source"], "user_report")
            self.assertEqual(saved["state"]["observed_dimensions"], ["stress"])
            for version in ("rolling_v1", "daily_v2"):
                output = io.StringIO()
                with redirect_stdout(output):
                    cli.main(
                        [
                            *base,
                            "trend",
                            "--version",
                            version,
                            "--at",
                            "2020-01-03T12:00:00+08:00",
                        ]
                    )
                trend = json.loads(output.getvalue())["trend"]
                self.assertEqual(trend["version"], version)
                if version == "daily_v2":
                    self.assertIsNone(trend["means"]["stress"])
                    self.assertEqual(
                        trend["sources"]["user_report"]["dimensions"]["stress"]["mean"],
                        0,
                    )
                else:
                    self.assertEqual(trend["means"]["stress"], 0)
            report_path.write_text(
                '{"timestamp":"2099-01-01T00:00:00Z","emotion":{"stress":0.4}}',
                encoding="utf-8",
            )
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(
                    [
                        *base,
                        "self-report",
                        "--input",
                        str(report_path),
                        "--history-scope",
                        "manual",
                    ]
                )
            self.assertEqual(len(owner.list_records()), 1)


if __name__ == "__main__":
    unittest.main()
