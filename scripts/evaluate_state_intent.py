"""Evaluate the two estimators on independently split fictional scenarios."""

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from statistics import mean, correlation
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from open_llm_vtuber.mental_health.llm_estimator import (  # noqa: E402
    LLMStateIntentEstimator,
    resolve_estimated_intent,
)  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.intent_estimator import IntentEstimator  # noqa: E402
from open_llm_vtuber.mental_health.schemas import PsychologicalState  # noqa: E402
from open_llm_vtuber.mental_health.long_term import observation_source  # noqa: E402

DIMS = ("stress", "anxiety", "low_mood")
INTENTS = (
    "venting",
    "seeking_practical_help",
    "seeking_clarification",
    "ending",
    "small_talk",
    "other",
)


def f1(pairs):
    tp = sum(a and b for a, b in pairs)
    denominator = sum(int(a) + int(b) for a, b in pairs)
    return 2 * tp / denominator if denominator else None


def metrics(pairs):
    scores = {}
    for k in DIMS:
        overlap = [
            abs(a[k] - b[k]) for a, b in pairs if a[k] is not None and b[k] is not None
        ]
        scores[k] = {
            "observed_f1": f1([(a[k] is not None, b[k] is not None) for a, b in pairs]),
            "mae": mean(overlap) if overlap else None,
            "paired_n": len(overlap),
        }
    per_class = [
        f1([(a["intent"] == c, b["intent"] == c) for a, b in pairs]) for c in INTENTS
    ]
    return {
        "n": len(pairs),
        "dimensions": scores,
        "observed_macro_f1": mean(v["observed_f1"] or 0 for v in scores.values()),
        "intent_macro_f1": mean(v or 0 for v in per_class),
        **{
            k + "_accuracy": mean(a[k] == b[k] for a, b in pairs)
            for k in ("intent", "advice_preference")
        },
    }


def ranks(numbers):
    groups = defaultdict(list)
    for index, value in enumerate(sorted(numbers), 1):
        groups[value].append(index)
    return [mean(groups[value]) for value in numbers]


def calibrate(path):
    daily = defaultdict(lambda: defaultdict(list))
    if path and path.is_file():
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for user, stamp, payload in db.execute(
                "SELECT user_id,timestamp,payload FROM states"
            ):
                state = PsychologicalState.model_validate_json(payload)
                if not state.timestamp_known:
                    continue
                day = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).date()
                for dim in state.observed_dimensions:
                    source = state.dimension_sources.get(dim, observation_source(state))
                    daily[user, day, dim][source].append(getattr(state.emotion, dim))
        finally:
            db.close()
    result = {}
    for dim in DIMS:
        pairs = [
            (mean(v["system_estimate"]), mean(v["user_report"]))
            for (_, _, d), v in daily.items()
            if d == dim and v.get("system_estimate") and v.get("user_report")
        ]
        x = [a for a, b in pairs]
        y = [b for a, b in pairs]
        valid = len(pairs) >= 3 and len(set(x)) > 1 and len(set(y)) > 1
        result[dim] = {
            "paired_days": len(x),
            "status": "可计算" if valid else "样本不足或无变异",
            "pearson": correlation(x, y) if valid else None,
            "spearman": correlation(ranks(x), ranks(y)) if valid else None,
            "mean_bias": mean(a - b for a, b in pairs) if pairs else None,
        }
    return result


def load_truth(cases, ratings):
    if not ratings:
        return
    with ratings.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    lookup = {r["id"]: r for r in rows}
    if len(rows) != len(lookup) or set(lookup) != {c["id"] for c in cases}:
        raise ValueError("Adjudicated file must cover every unique case ID")
    for c in cases:
        row = lookup[c["id"]]
        if (
            row["text"] != c["text"]
            or row["intent"] not in INTENTS
            or row["advice_preference"] not in ("requested", "declined", "unspecified")
        ):
            raise ValueError("Invalid adjudicated row " + c["id"])
        for k in DIMS:
            val = None if row[k].strip() == "null" else float(row[k])
            if val is not None and not 0 <= val <= 1:
                raise ValueError("Invalid dimension " + c["id"])
            c[k] = val
        c.update(intent=row["intent"], advice_preference=row["advice_preference"])


async def evaluate(args):
    cases = json.loads(
        (ROOT / "tests/fixtures/state_intent_eval.json").read_text("utf8")
    )
    load_truth(cases, args.adjudicated)
    secondary = None
    if args.reference:
        if not args.adjudicated:
            raise ValueError("--reference requires a primary human label file")
        secondary = deepcopy(cases)
        load_truth(secondary, args.reference)
    llm = LLMStateIntentEstimator(args.base_url, args.model, args.key, args.timeout)
    baseline = ContextStateEstimator()
    intent_rule = IntentEstimator()
    safety_guard = ContextSafetyGuard()
    groups = defaultdict(list)
    failures = defaultdict(Counter)
    try:
        for i, c in enumerate(cases, 1):
            safety = await safety_guard.check_input(c["text"])
            rule_intent = intent_rule.estimate(c["text"])
            for name, engine in (("rule", baseline), ("llm", llm)):
                state = await engine.estimate(c["text"], safety)
                intent = resolve_estimated_intent(rule_intent, state.interaction_intent)
                estimate = {
                    d: getattr(state.emotion, d)
                    if d in state.observed_dimensions
                    else None
                    for d in DIMS
                }
                estimate.update(
                    intent=intent.primary if intent.primary in INTENTS else "other",
                    advice_preference=intent.advice_preference,
                )
                groups[c["split"], name].append((c, estimate))
                if state.estimator_fallback_reason:
                    failures[c["split"]][state.estimator_fallback_reason] += 1
            if i % 40 == 0:
                print(i, flush=True)
    finally:
        await llm.aclose()
    data = {
        "dataset": "开发者构建的虚构句库",
        "labels": "independent_reviewers"
        if secondary
        else "adjudicated"
        if args.adjudicated
        else "draft",
        "model": args.model,
        "metrics": {
            s: {n: metrics(groups[s, n]) for n in ("rule", "llm")}
            for s in ("dev", "holdout")
        },
        "fallbacks": dict(failures),
        "calibration": calibrate(args.db),
        "predictions": {
            s: {
                n: [{"id": c["id"], **estimate} for c, estimate in groups[s, n]]
                for n in ("rule", "llm")
            }
            for s in ("dev", "holdout")
        },
    }
    if secondary:
        lookup = {c["id"]: c for c in secondary}
        data["reference_metrics"] = {
            s: {
                n: metrics(
                    [(lookup[c["id"]], estimate) for c, estimate in groups[s, n]]
                )
                for n in ("rule", "llm")
            }
            for s in ("dev", "holdout")
        }
    out = args.output
    out.parent.mkdir(exist_ok=True, parents=True)
    out.with_suffix(".json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf8"
    )
    lines = [
        "# 状态与意图抽取评测",
        "",
        f"开发者构建的虚构句库，共 {len(cases)} 条，标签状态为 {data['labels']}。模型为 {args.model}。默认运行规则版。",
        "",
        "同一批预测分别对照两份人工标签，强度分歧保留。以下主表对照第一份标签，第二份见同名 JSON。正式裁定待双方确认。"
        if secondary
        else "草案标签用于检查实现和发现误差。正式验收使用两人独立标注并处理分歧后的留出集。",
        "相同情境的所有变体位于同一划分。意图宏 F1 按六类平均，未覆盖类计零。未观测维度用 null，MAE 仅计算双方都有观测值的交集。",
        "",
        "| 数据集 | 方法 | 样本 | 观测宏 F1 | 意图宏 F1 | 意图准确率 | 建议偏好准确率 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for s, group in data["metrics"].items():
        for n, m in group.items():
            lines.append(
                f"| {s} | {n} | {m['n']} | {m['observed_macro_f1']:.3f} | {m['intent_macro_f1']:.3f} | {m['intent_accuracy']:.3f} | {m['advice_preference_accuracy']:.3f} |"
            )
    lines += [
        "",
        "逐维指标、MAE 样本数及回退次数见同名 JSON。模型指标包含规则回退。",
        "",
        "校准按用户、上海自然日和维度配对，分别计算日均值。",
    ]
    for dim, result in data["calibration"].items():
        lines.append(
            f"- {dim} 配对 {result['paired_days']} 个用户日，{result['status']}。"
        )
    out.write_text("\n".join(lines) + "\n", "utf8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:18082/v1")
    p.add_argument("--model", default="mental-health-orpo")
    p.add_argument("--key", default="local")
    p.add_argument("--timeout", type=float, default=15)
    p.add_argument("--db", type=Path)
    p.add_argument("--adjudicated", type=Path)
    p.add_argument("--reference", type=Path, help="Second independent human label file")
    p.add_argument(
        "--output", type=Path, default=ROOT / "docs/mental_health_state_intent_eval.md"
    )
    asyncio.run(evaluate(p.parse_args()))
