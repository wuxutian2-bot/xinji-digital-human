"""Deterministic daily_v2/rolling_v1 comparison using synthetic data only."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.mental_health.long_term import (  # noqa: E402
    summarize_daily_trend,
    summarize_trend,
)
from open_llm_vtuber.mental_health.schemas import PsychologicalState  # noqa: E402


def build_report(user_report_score=0.0):
    if not 0.0 <= user_report_score <= 1.0:
        raise ValueError("user_report_score must be between 0 and 1")
    now = datetime(2026, 9, 23, 4, tzinfo=timezone.utc)

    def state(days, score, *, minute=0, source="context_v2"):
        return PsychologicalState(
            timestamp=now - timedelta(days=days, minutes=minute),
            estimator_source=source,
            observed_dimensions=["stress"],
            emotion={"stress": score},
            topics=["work", "work"],
        )

    cases = {
        "unequal_daily_frequency": [state(0, 1, minute=i) for i in range(30)]
        + [state(1, 0), state(2, 0)],
        "single_day_is_insufficient": [state(0, 0.8, minute=i) for i in range(100)],
        "separate_sources": [state(i, 0.8) for i in range(3)]
        + [state(i, user_report_score, source="user_report") for i in range(3)],
        "calendar_boundary": [state(i, 0.8) for i in (6, 7, 8)],
        "unknown_legacy_source": [state(i, 0.8, source="legacy") for i in range(3)],
        "stale_observation": [state(30, 0.8)],
    }
    results = []
    for name, rows in cases.items():
        daily = summarize_daily_trend(rows, now)
        replay = summarize_daily_trend(rows + [rows[0]] * 100, now)
        assert daily.sources == replay.sources, name
        results.append(
            {
                "case": name,
                "input": [row.model_dump(mode="json") for row in rows],
                "rolling_v1": summarize_trend(rows, now).model_dump(mode="json"),
                "daily_v2": daily.model_dump(mode="json"),
                "exact_replay_invariant": True,
            }
        )
    sources = [
        "src/open_llm_vtuber/mental_health/long_term.py",
        "src/open_llm_vtuber/mental_health/schemas.py",
        "scripts/compare_daily_trends.py",
    ]
    return {
        "synthetic_only": True,
        "scenario_parameters": {"separate_sources_user_report_score": user_report_score},
        "as_of": now.isoformat(),
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sources
        },
        "interpretation": "Engineering comparison only; no model calls, user records, or clinical outcomes.",
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-report-score", type=float, default=0.0)
    args = parser.parse_args()
    report = build_report(args.user_report_score)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    for case in report["cases"]:
        print(
            json.dumps(
                {
                    "case": case["case"],
                    "rolling_v1_stress": case["rolling_v1"]["means"]["stress"],
                    "daily_v2_system_stress": case["daily_v2"]["means"]["stress"],
                    "replay_invariant": case["exact_replay_invariant"],
                }
            )
        )


if __name__ == "__main__":
    main()
