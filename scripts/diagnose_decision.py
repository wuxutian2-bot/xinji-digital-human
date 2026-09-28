"""Frozen, development-only factorial probes of actual Decision wire requests."""

import argparse
import asyncio
from collections import Counter
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
import sys
from time import perf_counter
from types import SimpleNamespace

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.decision_client import (  # noqa: E402
    OpenAICompatibleDecisionClient,
    RuleBasedDecisionClient,
)
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision  # noqa: E402
from open_llm_vtuber.mental_health.intent_estimator import IntentEstimator  # noqa: E402
from open_llm_vtuber.mental_health.long_term import summarize_daily_trend  # noqa: E402
from open_llm_vtuber.mental_health.schemas import (  # noqa: E402
    DecisionContext,
    PsychologicalState,
)

VARIANTS = ("baseline", "no_schema_defaults", "no_state_strategy", "both")
MODEL = "mental-health-decision-qwen2.5-1.5b"
SEED = 20260923


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, data):
    with Path(path).open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")


def remove_defaults(node):
    if isinstance(node, dict):
        node.pop("default", None)
        for value in node.values():
            remove_defaults(value)
    elif isinstance(node, list):
        for value in node:
            remove_defaults(value)


def transform_request(request, variant):
    """Experimental wire-only ablations; production client remains unchanged."""
    if variant not in VARIANTS:
        raise ValueError("Unknown diagnostic variant")
    result = copy.deepcopy(request)
    if variant in {"no_schema_defaults", "both"}:
        system = result["messages"][0]["content"]
        prefix = OpenAICompatibleDecisionClient._SYSTEM_PROMPT
        if not system.startswith(prefix):
            raise ValueError("Unexpected Decision prompt structure")
        schema_text, suffix = system[len(prefix) :].split(
            "\nDecision protocol version:", 1
        )
        schema = json.loads(schema_text)
        remove_defaults(schema)
        result["messages"][0]["content"] = (
            prefix
            + json.dumps(schema, ensure_ascii=False)
            + "\nDecision protocol version:"
            + suffix
        )
    if variant in {"no_state_strategy", "both"}:
        context = json.loads(result["messages"][1]["content"])
        context["current_state"].pop("interaction_strategy", None)
        for state in context.get("recent_states", []):
            state.pop("interaction_strategy", None)
        result["messages"][1]["content"] = json.dumps(
            context, ensure_ascii=False, separators=(",", ":")
        )
    return result


async def build_context(case, now):
    safety = await ContextSafetyGuard().check_input(case["text"])
    state = await ContextStateEstimator().estimate(case["text"], safety)
    state.timestamp = now
    history = []
    if case["history"] != "none":
        offset = 0 if case["history"] == "fresh" else 30
        history = [
            PsychologicalState(
                timestamp=now - timedelta(days=offset + day),
                estimator_source="context_v2",
                observed_dimensions=["stress"],
                emotion={"stress": 0.8},
                topics=["work"],
            )
            for day in (0, 1, 2)
        ]
    return DecisionContext(
        user_text=case["text"],
        current_state=state,
        safety=safety,
        interaction_intent=IntentEstimator().estimate(case["text"]),
        recent_states=history,
        long_term_trend=summarize_daily_trend(history, now).model_dump(mode="json"),
    )


class Recorder:
    def __init__(self, sdk, variant):
        self.sdk, self.variant, self.calls = sdk, variant, []

    async def create(self, **kwargs):
        request = transform_request(kwargs, self.variant)
        request["seed"] = SEED
        record = {
            "request": request,
            "raw_text": None,
            "finish_reason": None,
            "error_type": None,
        }
        self.calls.append(record)
        started = perf_counter()
        try:
            response = await self.sdk.chat.completions.create(**request)
            record["response_model"] = response.model
            record["usage"] = response.usage.model_dump() if response.usage else None
            if response.choices:
                record["raw_text"] = response.choices[0].message.content
                record["finish_reason"] = response.choices[0].finish_reason
            return response
        except BaseException as error:
            record["error_type"] = type(error).__name__
            raise
        finally:
            record["seconds"] = round(perf_counter() - started, 4)


async def run_case(sdk, case, context, variant):
    row = {
        "case_id": case["id"],
        "variant": variant,
        "expected": case["expected"],
        "calls": [],
        "error_type": None,
    }
    if context.safety.action == "escalate":
        row.update(
            source="safety_gate",
            parsed=None,
            final=None,
            proposed_match=None,
            final_match=None,
        )
        return row
    recorder = Recorder(sdk, variant)
    client = OpenAICompatibleDecisionClient(
        model=MODEL,
        base_url="http://127.0.0.1:8001/v1",
        llm_api_key="local",
        temperature=0,
        max_tokens=300,
        timeout_seconds=15,
        response_format="llama_json_schema",
        protocol_version=2,
        client=SimpleNamespace(chat=SimpleNamespace(completions=recorder)),
    )
    try:
        proposed = await client.decide(context)
        row["source"] = "model"
    except Exception as error:
        row["error_type"] = type(error).__name__
        proposed = await RuleBasedDecisionClient().decide(context)
        row["source"] = "fallback"
    final = coordinate_decision(proposed, context)
    row.update(
        calls=recorder.calls,
        parsed=proposed.model_dump(),
        final=final.model_dump(),
        coordination=final.trace.coordination.model_dump(),
        proposed_match=proposed.strategy.primary in case["expected"]
        if row["source"] == "model"
        else None,
        final_match=final.strategy.primary in case["expected"],
    )
    return row


def aggregate(rows):
    metrics = {}
    for variant in VARIANTS:
        selected = [r for r in rows if r["variant"] == variant]
        model = [r for r in selected if r["source"] == "model"]
        metrics[variant] = {
            "runs": len(selected),
            "requests": sum(len(r["calls"]) for r in selected),
            "valid": len(model),
            "fallbacks": sum(r["source"] == "fallback" for r in selected),
            "safety_bypasses": sum(r["source"] == "safety_gate" for r in selected),
            "raw_proposal_distribution": dict(
                Counter(r["parsed"]["strategy"]["primary"] for r in model)
            ),
            "proposed_matches": sum(r["proposed_match"] is True for r in model),
            "final_matches": sum(r["final_match"] is True for r in selected),
            "coordinator_changes": sum(
                r["parsed"]["strategy"] != r["final"]["strategy"] for r in model
            ),
        }
    return metrics


async def evaluate(args):
    fixture = json.loads(args.fixtures.read_text(encoding="utf-8"))
    if fixture.get("version") != 1 or not fixture["cases"]:
        raise ValueError("Unsupported or empty diagnostic fixture")
    cases = {c["id"]: c for c in fixture["cases"]}
    if len(cases) != len(fixture["cases"]) or any(
        c["history"] not in {"none", "fresh", "stale"} for c in cases.values()
    ):
        raise ValueError("Invalid diagnostic cases")
    now = datetime.fromisoformat(fixture["now"])
    contexts = {k: await build_context(c, now) for k, c in cases.items()}
    sources = [Path(__file__)] + sorted(
        (ROOT / "src/open_llm_vtuber/mental_health").glob("*.py")
    )
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    schedule, rng = [], random.Random(SEED)
    for repeat in range(1, args.repeats + 1):
        block = [
            {"repeat": repeat, "case_id": k, "variant": v}
            for k in cases
            for v in VARIANTS
        ]
        rng.shuffle(block)
        schedule.extend(block)
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(
        args.output / "manifest.json",
        {
            "schema_version": 1,
            "purpose": "development_diagnostic_not_quality_evaluation",
            "fixture": fixture,
            "fixture_sha256": sha(args.fixtures),
            "source_sha256": source_hashes,
            "contexts": {k: c.model_dump(mode="json") for k, c in contexts.items()},
            "schedule": schedule,
            "model": MODEL,
            "seed": SEED,
            "generation": {
                "temperature": 0,
                "max_tokens": 300,
                "timeout_seconds": 15,
                "response_format": "llama_json_schema",
            },
            "weights_sha256": sha(
                ROOT / "models/decision/qwen2.5-1.5b-instruct-q4_k_m.gguf"
            ),
            "server_sha256": sha(
                ROOT / "private/decision/llama-b10964-cpu/llama-server.exe"
            ),
            "limit": "Repeated synthetic scenarios are correlated; no quality or clinical conclusion. Fresh/stale history targets allow multiple strategies.",
        },
    )
    rows = []
    async with AsyncOpenAI(
        base_url="http://127.0.0.1:8001/v1", api_key="local", max_retries=0, timeout=15
    ) as sdk:
        available = await sdk.models.list()
        if MODEL not in {m.id for m in available.data}:
            raise ValueError("Unexpected local Decision model")
        first = next(k for k, c in contexts.items() if c.safety.action != "escalate")
        warmup = [
            await run_case(sdk, cases[first], contexts[first], "baseline")
            for _ in range(2)
        ]
        write_new(args.output / "warmup.json", warmup)
        for i, entry in enumerate(schedule, 1):
            k = entry["case_id"]
            row = {
                **await run_case(sdk, cases[k], contexts[k], entry["variant"]),
                "repeat": entry["repeat"],
            }
            write_new(args.output / f"run-{i:03d}.json", row)
            rows.append(row)
            print(
                json.dumps(
                    {
                        "done": i,
                        "total": len(schedule),
                        "case": k,
                        "variant": entry["variant"],
                        "source": row["source"],
                        "proposed": row["parsed"]["strategy"]["primary"]
                        if row["parsed"]
                        else None,
                    }
                ),
                flush=True,
            )
    if (
        source_hashes != {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
        or sha(args.fixtures)
        != json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))[
            "fixture_sha256"
        ]
    ):
        raise ValueError("Diagnostic source or fixtures changed during the run")
    report = {
        "status": "complete",
        "manifest_sha256": sha(args.output / "manifest.json"),
        "rows": rows,
        "metrics": aggregate(rows),
        "human_quality_review": "pending",
    }
    write_new(args.output / "report.json", report)
    print(json.dumps(report["metrics"], ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "tests/fixtures/decision_diagnostic_cases.json",
    )
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
