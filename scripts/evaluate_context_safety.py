"""Freeze context failures of the unchanged v1 rules on synthetic cases only."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.mental_health.safety_guard import RuleBasedSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.state_estimator import KeywordStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.schemas import SafetyAction  # noqa: E402
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402


def validate_cases(cases):
    if len(cases) < 80 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Need at least 80 unique cases")
    families = {"dev": set(), "holdout": set()}
    for case in cases:
        families[case["split"]].add(case["family"])
        expected = case["expected_escalation"]
        if expected is not None and type(expected) is not bool:
            raise ValueError("Invalid risk label")
        if case.get("critical") and expected is not True:
            raise ValueError("Critical cases must be labeled escalate")
        if not isinstance(case["text"], str) or not case["text"].strip():
            raise ValueError("Missing synthetic input")
    if not all(families.values()) or families["dev"] & families["holdout"]:
        raise ValueError("Development and holdout families must be disjoint")


def metrics(rows):
    counts = {key: 0 for key in ("tp", "tn", "fp", "fn")}
    errors = []
    critical_misses = []
    for row in rows:
        expected = row["expected_escalation"]
        if expected is not None:
            key = ("t" if row["escalated"] == expected else "f") + (
                "p" if row["escalated"] else "n"
            )
            counts[key] += 1
            if row["escalated"] != expected:
                errors.append(row["id"])
        if row.get("critical") and not row["escalated"]:
            critical_misses.append(row["id"])
    state_rows = [r for r in rows if "expected_observed" in r]
    return {
        "count": len(rows),
        "confusion": counts,
        "uncertain_label_count": sum(r["expected_escalation"] is None for r in rows),
        "uncertain_label_ratio": sum(r["expected_escalation"] is None for r in rows)
        / len(rows)
        if rows
        else None,
        "classifier_unknown_ratio": 0 if rows else None,
        "critical_false_negative_ids": critical_misses,
        "risk_mismatch_ids": errors,
        "state_cases_checked": len(state_rows),
        "state_mismatch_ids": [
            r["id"]
            for r in state_rows
            if set(r["observed_dimensions"]) != set(r["expected_observed"])
        ],
    }


async def evaluate(cases, contextual=False):
    guard, estimator = (
        (ContextSafetyGuard(), ContextStateEstimator())
        if contextual
        else (RuleBasedSafetyGuard(), KeywordStateEstimator())
    )
    rows = []
    for case in cases:
        previous = None
        if contextual:
            for text in case.get("prior", []):
                previous = await guard.check_input_with_context(text, previous)
            safety = await guard.check_input_with_context(case["text"], previous)
        else:
            safety = await guard.check_input(case["text"])
        state = await estimator.estimate(case["text"], safety)
        rows.append(
            {
                **case,
                "escalated": safety.action == SafetyAction.ESCALATE,
                "risk_level": safety.risk_level.value,
                "signals": safety.signals,
                "observed_dimensions": state.observed_dimensions,
                "prior_context_used": bool(contextual and case.get("prior")),
                "context_evidence": [e.model_dump() for e in safety.context_evidence],
                "emotion": state.emotion.model_dump(),
            }
        )
    return {
        "cases": rows,
        "metrics": metrics(rows),
        "by_split": {
            key: metrics([r for r in rows if r["split"] == key])
            for key in ("dev", "holdout")
        },
        "by_family": {
            key: metrics([r for r in rows if r["family"] == key])
            for key in sorted({r["family"] for r in rows})
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "tests/fixtures/context_safety_cases.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "tests/fixtures/context_safety_manifest.json",
    )
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--implementation", choices=("baseline", "context_v2"), default="baseline"
    )
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError("Choose a new report path")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if (
            hashlib.sha256(args.fixtures.read_bytes()).hexdigest()
            != manifest["fixtures_sha256"]
        ):
            raise ValueError("Fixture changed after freeze")
        for relative, digest in manifest["baseline_source_sha256"].items():
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
                raise ValueError(
                    "Baseline implementation changed; do not relabel new rules as baseline"
                )
        cases = json.loads(args.fixtures.read_text(encoding="utf-8"))["cases"]
        validate_cases(cases)
        selected = [c for c in cases if args.split == "all" or c["split"] == args.split]
        sources = list((ROOT / "src/open_llm_vtuber/mental_health").glob("*.py"))
        hashes = {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        }
        contextual = args.implementation == "context_v2"
        report = asyncio.run(evaluate(selected, contextual))
        if contextual:
            baseline = asyncio.run(evaluate(selected))
            before = set(baseline["metrics"]["critical_false_negative_ids"])
            report["new_critical_false_negative_ids"] = sorted(
                set(report["metrics"]["critical_false_negative_ids"]) - before
            )
            report["baseline_metrics"] = baseline["metrics"]
        report.update(
            created_at=datetime.now(timezone.utc).isoformat(),
            mode="context_v2" if contextual else "frozen_rule_v1",
            source_sha256=hashes,
            sources_unchanged_during_run=all(
                hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                for p, h in hashes.items()
            ),
            fixture_manifest=manifest,
            evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            limitations=[
                "Synthetic developer labels, no independent clinical review",
                "Family split is authored separation, not proven semantic independence",
                "Old rules ignore prior turns; context_v2 uses previous structured safety evidence",
                "Context evidence uncertainty is distinct from an escalation label; classifier returns no unknown label",
            ],
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps(report["metrics"], ensure_ascii=False))
        return (
            1
            if report["metrics"]["risk_mismatch_ids"]
            or report["metrics"]["state_mismatch_ids"]
            else 0
        )
    except Exception as error:
        print(f"Context evaluation failed ({type(error).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
