"""Audit E3c wire, local intent, rules, model proposals and arbitration."""

import argparse
import asyncio
import json
from pathlib import Path

from decision_intent_contract import transform, VARIANTS
from evaluate_intent_contract import aggregate, screening_gate
from diagnose_decision import sha, write_new, MODEL, SEED
from open_llm_vtuber.mental_health.decision_client import (
    OpenAICompatibleDecisionClient,
    RuleBasedDecisionClient,
    constrain_expression,
)
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision
from open_llm_vtuber.mental_health.schemas import DecisionContext, DecisionResult


async def validate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if (
        report["status"] != "complete"
        or report["manifest_sha256"] != sha(directory / "manifest.json")
        or report["split"] != manifest["split"]
    ):
        raise ValueError("Incomplete or mismatched report")
    rows, schedule = report["rows"], manifest["schedule"]
    identities = [(r["repeat"], r["case_id"], r["variant"]) for r in rows]
    cases = {c["id"]: c for c in manifest["fixture"]["cases"]}
    repeats = sorted({r["repeat"] for r in rows})
    if not repeats or repeats != list(range(1, len(repeats) + 1)) or len(repeats) > 3:
        raise ValueError("Invalid repeats")
    if manifest["split"] == "holdout" and (
        len(repeats) != 3
        or not manifest["candidate_freeze_sha256"]
        or manifest["fixture"].get("candidate_freeze_sha256")
        != manifest["candidate_freeze_sha256"]
    ):
        raise ValueError("Holdout requires three repeats and candidate binding")
    if (
        len(set(identities)) != len(rows)
        or set(identities)
        != {
            (repeat, case, variant)
            for repeat in repeats
            for case in cases
            for variant in VARIANTS
        }
        or identities != [(r["repeat"], r["case_id"], r["variant"]) for r in schedule]
    ):
        raise ValueError("Incomplete or reordered design")
    contexts = {
        k: DecisionContext.model_validate(v) for k, v in manifest["contexts"].items()
    }
    base = {
        (r["repeat"], r["case_id"]): r for r in rows if r["variant"] == "contract_v1"
    }
    checks, signatures = 0, {}
    for index, row in enumerate(rows, 1):
        if (
            row
            != json.loads(
                (directory / f"run-{index:03d}.json").read_text(encoding="utf-8")
            )
            or row["expected"] != cases[row["case_id"]]["expected"]
        ):
            raise ValueError("Run record/target mismatch")
        context = contexts[row["case_id"]]
        if row["local_intent"] != context.interaction_intent.model_dump():
            raise ValueError("Local intent mismatch")
        if context.safety.action == "escalate":
            if row["rule_proposal"] is not None or row["rule_final"] is not None:
                raise ValueError("Safety bypass cannot claim rules executed")
        else:
            rule = await RuleBasedDecisionClient().decide(context)
            if (
                row["rule_proposal"] != rule.model_dump()
                or row["rule_final"] != coordinate_decision(rule, context).model_dump()
            ):
                raise ValueError("Rule baseline mismatch")
        if context.safety.action == "escalate":
            if (
                row["source"] != "safety_gate"
                or row["calls"]
                or row["parsed"] is not None
                or row["final"] is not None
                or row["proposed_match"] is not None
                or row["final_match"] is not None
            ):
                raise ValueError("Safety bypass violated")
            continue
        if row["source"] not in {"model", "fallback"} or len(row["calls"]) != 1:
            raise ValueError("Expected one request")
        call = row["calls"][0]
        request = call["request"]
        original = base[(row["repeat"], row["case_id"])]["calls"][0]["request"]
        if request != transform(original, row["variant"]):
            raise ValueError("Request changed outside named variant")
        if (
            request["model"] != MODEL
            or request["seed"] != SEED
            or request["temperature"] != 0
            or request["max_tokens"] != 300
            or request["stream"] is not False
        ):
            raise ValueError("Generation configuration mismatch")
        identity = (row["case_id"], row["variant"])
        if identity in signatures and signatures[identity] != request:
            raise ValueError("Repeated request content changed")
        signatures[identity] = request
        checks += 1
        proposed = DecisionResult.model_validate(row["parsed"], strict=True)
        if row["source"] == "model":
            if call["error_type"] is not None or call["finish_reason"] != "stop":
                raise ValueError("Failed response labeled as success")
            raw = DecisionResult.model_validate(
                OpenAICompatibleDecisionClient._extract_json(call["raw_text"]),
                strict=True,
            )
            if constrain_expression(raw, context).model_dump() != row["parsed"] or row[
                "proposed_match"
            ] != (raw.strategy.primary in row["expected"]):
                raise ValueError("Raw proposal mismatch")
        elif row["proposed_match"] is not None:
            raise ValueError("Fallback counted as proposal match")
        final = coordinate_decision(proposed, context)
        if (
            final.model_dump() != row["final"]
            or final.trace.coordination.model_dump() != row["coordination"]
            or row["final_match"] != (final.strategy.primary in row["expected"])
        ):
            raise ValueError("Arbitration mismatch")
    if report["screening_gate"] != screening_gate(report, manifest["fixture"]):
        raise ValueError("Screening gate mismatch")
    if report["metrics"] != aggregate(rows):
        raise ValueError("Aggregate mismatch")
    return {
        "status": "validated",
        "request_boundary_checks": checks,
        "identical_repeat_groups": len(signatures),
        "report_sha256": sha(directory / "report.json"),
        "manifest_sha256": sha(directory / "manifest.json"),
        "validator_sha256": sha(__file__),
        "screening_gate": screening_gate(report, manifest["fixture"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(validate(args.experiment))
    write_new(args.output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
