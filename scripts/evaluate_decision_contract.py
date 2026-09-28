"""E3b development and once-only holdout runs with an immutable candidate freeze."""

import argparse
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import random
from types import SimpleNamespace

from openai import AsyncOpenAI

import diagnose_decision as diagnostic
from decision_contract import transform, VARIANTS
from open_llm_vtuber.mental_health.schemas import StrategyDecision

ROOT = diagnostic.ROOT


def sources():
    paths = [
        Path(__file__),
        ROOT / "scripts/decision_contract.py",
        ROOT / "scripts/diagnose_decision.py",
    ]
    paths += sorted((ROOT / "src/open_llm_vtuber/mental_health").glob("*.py"))
    return {p.relative_to(ROOT).as_posix(): diagnostic.sha(p) for p in paths}


def freeze(path):
    diagnostic.write_new(
        path,
        {
            "schema_version": 1,
            "candidate": "contract_v1",
            "source_sha256": sources(),
            "created_at": datetime.now().astimezone().isoformat(),
            "purpose": "Freeze candidate before authoring/using new holdout fixtures",
        },
    )


class Wire:
    """Capture exactly what is sent to the SDK, after the experimental transform."""

    def __init__(self, sdk, variant):
        self.sdk, self.variant, self.requests = sdk, variant, []

    async def create(self, **kwargs):
        request = transform(kwargs, self.variant)
        self.requests.append(request)
        return await self.sdk.chat.completions.create(**request)


async def run_case(sdk, case, context, variant):
    wire = Wire(sdk, variant)
    wrapped = SimpleNamespace(chat=SimpleNamespace(completions=wire))
    row = await diagnostic.run_case(wrapped, case, context, "baseline")
    if len(row["calls"]) != len(wire.requests):
        raise ValueError("Request capture mismatch")
    for call, request in zip(row["calls"], wire.requests):
        call["request"] = request
    row["variant"] = variant
    return row


def aggregate(rows):
    result = {}
    for variant in VARIANTS:
        group = [r for r in rows if r["variant"] == variant]
        model = [r for r in group if r["source"] == "model"]
        result[variant] = {
            "runs": len(group),
            "requests": sum(len(r["calls"]) for r in group),
            "valid": len(model),
            "fallbacks": sum(r["source"] == "fallback" for r in group),
            "safety_bypasses": sum(r["source"] == "safety_gate" for r in group),
            "proposed_matches": sum(r["proposed_match"] is True for r in model),
            "final_matches": sum(r["final_match"] is True for r in group),
            "proposal_distribution": dict(
                Counter(r["parsed"]["strategy"]["primary"] for r in model)
            ),
        }
    return result


def validate_fixture(fixture):
    if (
        fixture.get("version") != 1
        or not isinstance(fixture.get("cases"), list)
        or not fixture["cases"]
    ):
        raise ValueError("Unsupported fixture")
    cases = {c["id"]: c for c in fixture["cases"]}
    if len(cases) != len(fixture["cases"]):
        raise ValueError("Duplicate case ID")
    for case in cases.values():
        if (
            not isinstance(case["text"], str)
            or not case["text"].strip()
            or case["history"] not in {"none", "fresh", "stale"}
        ):
            raise ValueError("Invalid diagnostic case")
        for strategy in case["expected"]:
            StrategyDecision(primary=strategy)
    return cases


def markdown(report, fixture):
    lines = [
        "# E3b 策略契约对照",
        "",
        f"数据划分：{report['split']}。仅虚构策略选择标签，人工对话质量仍待评。",
        "",
        "| 变体 | 请求 | 合法 | 原始匹配 | 协调后匹配 | 回退 | Safety绕过 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for v, m in report["metrics"].items():
        lines.append(
            f"| {v} | {m['requests']} | {m['valid']} | {m['proposed_matches']} | {m['final_matches']} | {m['fallbacks']} | {m['safety_bypasses']} |"
        )
    lines += ["", "| 案例 | baseline | both | contract_v1 |", "|---|---|---|---|"]
    for case in fixture["cases"]:
        cells = []
        for variant in VARIANTS:
            rows = [
                r
                for r in report["rows"]
                if r["case_id"] == case["id"] and r["variant"] == variant
            ]
            counts = Counter(
                r["parsed"]["strategy"]["primary"]
                if r["source"] == "model"
                else r["source"]
                for r in rows
            )
            cells.append(", ".join(f"{k} × {v}" for k, v in counts.items()))
        lines.append(f"| {case['id']} | {' | '.join(cells)} |")
    lines += [
        "",
        "重复输出相关；相同seed不保证完全复现。策略匹配不是临床或对话质量结论，规则协调后匹配不能充当模型原始能力。",
        "",
    ]
    return "\n".join(lines)


async def evaluate(args):
    fixture = json.loads(args.fixtures.read_text(encoding="utf-8"))
    cases = validate_fixture(fixture)
    source_hashes, fixture_hash = sources(), diagnostic.sha(args.fixtures)
    candidate = None
    if args.split == "holdout":
        if not args.freeze:
            raise ValueError("Holdout requires a frozen candidate")
        candidate = json.loads(args.freeze.read_text(encoding="utf-8"))
        if (
            candidate["source_sha256"] != source_hashes
            or candidate["candidate"] != "contract_v1"
        ):
            raise ValueError("Candidate changed after freeze")
        if fixture.get("split") != "holdout" or fixture.get(
            "candidate_freeze_sha256"
        ) != diagnostic.sha(args.freeze):
            raise ValueError("Holdout fixture must bind the prior candidate freeze")
        # A failed/partial holdout is also an exposure: do not silently retry it.
        marker = args.freeze.with_suffix(".holdout-started.json")
        if marker.exists():
            raise ValueError("This frozen candidate already started its holdout")
    now = datetime.fromisoformat(fixture["now"])
    contexts = {k: await diagnostic.build_context(c, now) for k, c in cases.items()}
    schedule, rng = [], random.Random(diagnostic.SEED)
    for repeat in range(1, args.repeats + 1):
        block = [
            {"repeat": repeat, "case_id": k, "variant": v}
            for k in cases
            for v in VARIANTS
        ]
        rng.shuffle(block)
        schedule += block
    args.output.mkdir(parents=True, exist_ok=False)
    if args.split == "holdout":
        diagnostic.write_new(
            marker,
            {
                "fixture_sha256": fixture_hash,
                "output": str(args.output),
                "candidate_freeze_sha256": diagnostic.sha(args.freeze),
            },
        )
    manifest = {
        "schema_version": 1,
        "split": args.split,
        "fixture": fixture,
        "fixture_sha256": fixture_hash,
        "source_sha256": source_hashes,
        "candidate_freeze_sha256": diagnostic.sha(args.freeze) if candidate else None,
        "contexts": {k: v.model_dump(mode="json") for k, v in contexts.items()},
        "schedule": schedule,
        "model": diagnostic.MODEL,
        "seed": diagnostic.SEED,
        "generation": {
            "temperature": 0,
            "max_tokens": 300,
            "timeout_seconds": 15,
            "response_format": "llama_json_schema",
        },
        "weights_sha256": diagnostic.sha(
            ROOT / "models/decision/qwen2.5-1.5b-instruct-q4_k_m.gguf"
        ),
        "server_sha256": diagnostic.sha(
            ROOT / "private/decision/llama-b10964-cpu/llama-server.exe"
        ),
    }
    diagnostic.write_new(args.output / "manifest.json", manifest)
    rows = []
    async with AsyncOpenAI(
        base_url="http://127.0.0.1:8001/v1", api_key="local", max_retries=0, timeout=15
    ) as sdk:
        if diagnostic.MODEL not in {m.id for m in (await sdk.models.list()).data}:
            raise ValueError("Unexpected Decision model")
        first = next(k for k, c in contexts.items() if c.safety.action != "escalate")
        warmup = [
            await run_case(sdk, cases[first], contexts[first], v)
            for v in ("baseline", "contract_v1")
        ]
        diagnostic.write_new(args.output / "warmup.json", warmup)
        for index, entry in enumerate(schedule, 1):
            key = entry["case_id"]
            row = {
                **await run_case(sdk, cases[key], contexts[key], entry["variant"]),
                "repeat": entry["repeat"],
            }
            diagnostic.write_new(args.output / f"run-{index:03d}.json", row)
            rows.append(row)
            print(
                json.dumps(
                    {
                        "done": index,
                        "total": len(schedule),
                        "case": key,
                        "variant": entry["variant"],
                        "source": row["source"],
                        "match": row["proposed_match"],
                    }
                ),
                flush=True,
            )
    if sources() != source_hashes or diagnostic.sha(args.fixtures) != fixture_hash:
        raise ValueError("Source or fixtures changed during experiment")
    report = {
        "status": "complete",
        "split": args.split,
        "manifest_sha256": diagnostic.sha(args.output / "manifest.json"),
        "rows": rows,
        "metrics": aggregate(rows),
        "human_quality_review": "pending",
    }
    diagnostic.write_new(args.output / "report.json", report)
    with (args.output / "summary.md").open("x", encoding="utf-8") as file:
        file.write(markdown(report, fixture))
    print(json.dumps(report["metrics"]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freezing = sub.add_parser("freeze")
    freezing.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--fixtures", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--split", choices=("development", "holdout"), required=True)
    run.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    run.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output)
    else:
        asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
