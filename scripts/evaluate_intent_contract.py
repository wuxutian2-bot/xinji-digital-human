"""E3c v1/v2 comparison with separate rule, model and coordinator evidence."""

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
from decision_intent_contract import from_baseline, VARIANTS
from evaluate_decision_contract import validate_fixture

ROOT = diagnostic.ROOT


def sources():
    paths = [Path(__file__)] + [
        ROOT / "scripts" / name
        for name in (
            "decision_intent_contract.py",
            "decision_contract.py",
            "diagnose_decision.py",
            "evaluate_decision_contract.py",
        )
    ]
    paths += sorted((ROOT / "src/open_llm_vtuber/mental_health").glob("*.py"))
    return {p.relative_to(ROOT).as_posix(): diagnostic.sha(p) for p in paths}


def freeze(path):
    diagnostic.write_new(
        path,
        {
            "schema_version": 1,
            "candidate": "contract_v2",
            "source_sha256": sources(),
            "created_at": datetime.now().astimezone().isoformat(),
        },
    )


def check_holdout(args, fixture, hashes):
    if args.split != "holdout":
        if fixture.get("split") != "development":
            raise ValueError("Development must not relabel an exposed holdout")
        return None
    if args.repeats != 3 or not args.freeze:
        raise ValueError("Holdout needs three repeats and a frozen candidate")
    frozen = json.loads(args.freeze.read_text(encoding="utf-8"))
    if frozen["candidate"] != "contract_v2" or frozen["source_sha256"] != hashes:
        raise ValueError("Candidate changed since freeze")
    if fixture.get("split") != "holdout" or fixture.get(
        "candidate_freeze_sha256"
    ) != diagnostic.sha(args.freeze):
        raise ValueError("Holdout is not bound to this candidate")
    marker = args.freeze.with_suffix(".holdout-started.json")
    if marker.exists():
        raise ValueError("Candidate holdout already started; do not repeat exposure")
    return marker


class Wire:
    def __init__(self, sdk, variant):
        self.sdk, self.variant, self.requests = sdk, variant, []

    async def create(self, **kwargs):
        request = from_baseline(kwargs, self.variant)
        self.requests.append(request)
        return await self.sdk.chat.completions.create(**request)


async def run_case(sdk, case, context, variant):
    if variant not in VARIANTS:
        raise ValueError("Unsupported variant")
    wire = Wire(sdk, variant)
    row = await diagnostic.run_case(
        SimpleNamespace(chat=SimpleNamespace(completions=wire)),
        case,
        context,
        "baseline",
    )
    if len(row["calls"]) != len(wire.requests):
        raise ValueError("Wire capture mismatch")
    for call, request in zip(row["calls"], wire.requests):
        call["request"] = request
    row["variant"] = variant
    row["local_intent"] = context.interaction_intent.model_dump()
    row["rule_proposal"] = None
    row["rule_final"] = None
    if context.safety.action != "escalate":
        proposed = await diagnostic.RuleBasedDecisionClient().decide(context)
        final = diagnostic.coordinate_decision(proposed, context)
        row["rule_proposal"] = proposed.model_dump()
        row["rule_final"] = final.model_dump()
    return row


def aggregate(rows):
    metrics = {}
    for variant in VARIANTS:
        group = [r for r in rows if r["variant"] == variant]
        normal = [r for r in group if r["expected"]]
        model = [r for r in normal if r["source"] == "model"]
        unknown = [r for r in normal if r["local_intent"]["primary"] == "unknown"]
        metrics[variant] = {
            "runs": len(group),
            "scheduled_normal": len(normal),
            "requests": sum(len(r["calls"]) for r in group),
            "valid": len(model),
            "fallbacks": sum(r["source"] == "fallback" for r in group),
            "safety_bypasses": sum(r["source"] == "safety_gate" for r in group),
            "proposed_matches": sum(
                r["source"] == "model" and r["proposed_match"] is True for r in normal
            ),
            "final_matches": sum(r["final_match"] is True for r in normal),
            "rule_proposed_matches": sum(
                r["rule_proposal"] is not None
                and r["rule_proposal"]["strategy"]["primary"] in r["expected"]
                for r in normal
            ),
            "rule_final_matches": sum(
                r["rule_final"] is not None
                and r["rule_final"]["strategy"]["primary"] in r["expected"]
                for r in normal
            ),
            "unknown_rows": len(unknown),
            "unknown_proposed_matches": sum(
                r["source"] == "model" and r["proposed_match"] is True for r in unknown
            ),
            "distribution": dict(
                Counter(r["parsed"]["strategy"]["primary"] for r in model)
            ),
        }
    return metrics


def screening_gate(report, fixture):
    policy = fixture.get("acceptance")
    if not policy:
        return None
    metrics = report["metrics"]["contract_v2"]
    count = metrics["scheduled_normal"]
    raw = metrics["proposed_matches"] / count if count else 0
    valid = metrics["valid"] / count if count else 0
    failures = [
        {"case_id": r["case_id"], "repeat": r["repeat"]}
        for r in report["rows"]
        if r["variant"] == "contract_v2"
        and r["case_id"] in policy["critical_case_ids"]
        and (r["source"] != "model" or r["proposed_match"] is not True)
    ]
    safety = [
        {"case_id": r["case_id"], "repeat": r["repeat"], "variant": r["variant"]}
        for r in report["rows"]
        if not r["expected"] and (r["source"] != "safety_gate" or r["calls"])
    ]
    return {
        "status": "passed"
        if raw >= policy["min_raw_match_rate"]
        and valid >= policy["min_valid_rate"]
        and not failures
        and not safety
        else "failed",
        "raw_match_rate": raw,
        "valid_rate": valid,
        "critical_failures": failures,
        "safety_failures": safety,
        "human_quality_review": "pending",
    }


def markdown(report, fixture):
    lines = [
        "# E3c 自然诉求与unknown边界",
        "",
        f"划分：{report['split']}；虚构内部实验，质量评阅待做。",
        "",
        "| 提示 | 请求 | 原始匹配 | 协调后匹配 | 规则原始/协调后匹配 | unknown项/原始匹配 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for v, m in report["metrics"].items():
        lines.append(
            f"| {v} | {m['requests']} | {m['proposed_matches']}/{m['scheduled_normal']} | {m['final_matches']} | {m['rule_proposed_matches']}/{m['rule_final_matches']} | {m['unknown_rows']}/{m['unknown_proposed_matches']} |"
        )
    lines += ["", "| 案例 | 本机诉求 | v1原始提议 | v2原始提议 |", "|---|---|---|---|"]
    for case in fixture["cases"]:
        selected = [r for r in report["rows"] if r["case_id"] == case["id"]]
        cells = []
        for variant in VARIANTS:
            counts = Counter(
                r["parsed"]["strategy"]["primary"]
                if r["source"] == "model"
                else r["source"]
                for r in selected
                if r["variant"] == variant
            )
            cells.append(", ".join(f"{k} × {v}" for k, v in counts.items()))
        lines.append(
            f"| {case['id']} | {selected[0]['local_intent']['primary']} | {' | '.join(cells)} |"
        )
    lines += [
        "",
        "筛查结果：" + json.dumps(report["screening_gate"], ensure_ascii=False),
        "",
        "重复输出不是独立病例；不输出质量或临床收益结论。unknown只表示本机未确定，不能自动等同于无诉求或同意建议。",
        "",
    ]
    return "\n".join(lines)


async def evaluate(args):
    fixture = json.loads(args.fixtures.read_text(encoding="utf-8"))
    cases = validate_fixture(fixture)
    hashes, fixture_hash = sources(), diagnostic.sha(args.fixtures)
    marker = check_holdout(args, fixture, hashes)
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
    if marker:
        diagnostic.write_new(
            marker,
            {
                "fixture_sha256": fixture_hash,
                "candidate_freeze_sha256": diagnostic.sha(args.freeze),
                "output": str(args.output),
            },
        )
    manifest = {
        "schema_version": 1,
        "split": args.split,
        "fixture": fixture,
        "fixture_sha256": fixture_hash,
        "source_sha256": hashes,
        "candidate_freeze_sha256": diagnostic.sha(args.freeze) if marker else None,
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
            raise ValueError("Unexpected Decision service")
        first = next(k for k, c in contexts.items() if c.safety.action != "escalate")
        diagnostic.write_new(
            args.output / "warmup.json",
            [await run_case(sdk, cases[first], contexts[first], v) for v in VARIANTS],
        )
        for i, entry in enumerate(schedule, 1):
            k = entry["case_id"]
            row = {
                **await run_case(sdk, cases[k], contexts[k], entry["variant"]),
                "repeat": entry["repeat"],
            }
            diagnostic.write_new(args.output / f"run-{i:03d}.json", row)
            rows.append(row)
            print(
                json.dumps(
                    {
                        "done": i,
                        "total": len(schedule),
                        "case": k,
                        "variant": entry["variant"],
                        "source": row["source"],
                        "match": row["proposed_match"],
                    }
                ),
                flush=True,
            )
    if sources() != hashes or diagnostic.sha(args.fixtures) != fixture_hash:
        raise ValueError("Experiment changed during run")
    report = {
        "status": "complete",
        "split": args.split,
        "manifest_sha256": diagnostic.sha(args.output / "manifest.json"),
        "rows": rows,
        "metrics": aggregate(rows),
        "human_quality_review": "pending",
    }
    report["screening_gate"] = screening_gate(report, fixture)
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
    run.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    run.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output)
    else:
        asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
