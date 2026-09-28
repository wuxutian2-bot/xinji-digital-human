"""Validate recorded E3 probes and export descriptive, case-level findings."""

import argparse
from collections import Counter
import json
from pathlib import Path

from diagnose_decision import aggregate, sha, transform_request, write_new, VARIANTS
from open_llm_vtuber.mental_health.decision_client import (
    OpenAICompatibleDecisionClient,
    constrain_expression,
)
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision
from open_llm_vtuber.mental_health.schemas import DecisionContext, DecisionResult


def validate(directory):
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if report["status"] != "complete" or report["manifest_sha256"] != sha(
        directory / "manifest.json"
    ):
        raise ValueError("Incomplete or mismatched diagnostic report")
    rows, schedule = report["rows"], manifest["schedule"]
    identities = [(r["repeat"], r["case_id"], r["variant"]) for r in rows]
    if identities != [
        (r["repeat"], r["case_id"], r["variant"]) for r in schedule
    ] or len(set(identities)) != len(rows):
        raise ValueError("Missing, reordered or duplicate diagnostic rows")
    cases = {c["id"]: c for c in manifest["fixture"]["cases"]}
    repeats = sorted({r["repeat"] for r in rows})
    if not repeats or repeats != list(range(1, len(repeats) + 1)) or len(repeats) > 3:
        raise ValueError("Invalid diagnostic repeats")
    if set(identities) != {
        (repeat, case, variant)
        for repeat in repeats
        for case in cases
        for variant in VARIANTS
    }:
        raise ValueError("Incomplete factorial design")
    contexts = {
        k: DecisionContext.model_validate(v) for k, v in manifest["contexts"].items()
    }
    baselines = {
        (r["repeat"], r["case_id"]): r for r in rows if r["variant"] == "baseline"
    }
    checks = 0
    for index, row in enumerate(rows, 1):
        if row != json.loads(
            (directory / f"run-{index:03d}.json").read_text(encoding="utf-8")
        ):
            raise ValueError("Report does not match per-run record")
        context = contexts[row["case_id"]]
        if row["expected"] != cases[row["case_id"]]["expected"]:
            raise ValueError("Target was changed after freezing")
        if context.safety.action == "escalate":
            if (
                row["source"] != "safety_gate"
                or row["calls"]
                or row["parsed"] is not None
                or row["final"] is not None
            ):
                raise ValueError("Safety gate must bypass all model work")
            continue
        if row["source"] not in {"model", "fallback"} or len(row["calls"]) != 1:
            raise ValueError("Expected exactly one Decision request")
        call = row["calls"][0]
        base = baselines[(row["repeat"], row["case_id"])]["calls"][0]["request"]
        if call["request"] != transform_request(base, row["variant"]):
            raise ValueError("Factorial probe changed unrelated request fields")
        checks += 1
        proposed = DecisionResult.model_validate(row["parsed"], strict=True)
        if row["source"] == "model":
            if call["error_type"] is not None or call["finish_reason"] != "stop":
                raise ValueError(
                    "Failed or truncated response labeled as model success"
                )
            raw = DecisionResult.model_validate(
                OpenAICompatibleDecisionClient._extract_json(call["raw_text"]),
                strict=True,
            )
            if constrain_expression(raw, context).model_dump() != row["parsed"]:
                raise ValueError("Parsed result is not the recorded model proposal")
            if row["proposed_match"] != (raw.strategy.primary in row["expected"]):
                raise ValueError("Incorrect raw proposal match")
        elif row["proposed_match"] is not None:
            raise ValueError("Fallback cannot count as a model proposal match")
        final = coordinate_decision(proposed, context)
        if (
            final.model_dump() != row["final"]
            or final.trace.coordination.model_dump() != row["coordination"]
        ):
            raise ValueError("Recorded arbitration differs from the local coordinator")
        if row["final_match"] != (final.strategy.primary in row["expected"]):
            raise ValueError("Incorrect final match")
    if report["metrics"] != aggregate(rows):
        raise ValueError("Metrics do not match recorded rows")
    return report, manifest, checks


def render(report, manifest, checks):
    lines = [
        "# E3 Decision 输入消融：开发集诊断",
        "",
        f"输入变更边界核对通过 {checks} 次请求。原始输出、解析与协调结果一致；Safety绕过单列。",
        "",
        "这是虚构开发场景上的定位实验。重复生成不等于独立样本；匹配预设可接受策略不等于对话质量或临床收益。历史三例允许多种合理策略，不要求有效历史必然改变策略。",
        "",
        "| 变体 | 正常请求 | 合法 | 回退 | 原始提议匹配 | 协调后匹配 | 协调改变策略字段 | Safety绕过 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant, metric in report["metrics"].items():
        lines.append(
            f"| {variant} | {metric['requests']} | {metric['valid']} | {metric['fallbacks']} | {metric['proposed_matches']} | {metric['final_matches']} | {metric['coordinator_changes']} | {metric['safety_bypasses']} |"
        )
    lines += [
        "",
        "## 逐案例原始模型提议",
        "",
        "| 案例 | 可接受策略 | baseline | no_schema_defaults | no_state_strategy | both |",
        "|---|---|---|---|---|---|",
    ]
    for case in manifest["fixture"]["cases"]:
        cells = []
        for variant in VARIANTS:
            counts = Counter(
                r["parsed"]["strategy"]["primary"]
                if r["source"] == "model"
                else r["source"]
                for r in report["rows"]
                if r["case_id"] == case["id"] and r["variant"] == variant
            )
            cells.append(", ".join(f"{k} × {v}" for k, v in sorted(counts.items())))
        lines.append(
            f"| {case['id']} | {', '.join(case['expected']) or 'Safety绕过'} | {' | '.join(cells)} |"
        )
    lines += [
        "",
        "## 解释边界",
        "",
        "- 四组生成schema保持相同；只改变系统提示词中的default字段、输入状态中的interaction_strategy字段。",
        "- 当前状态中的策略是状态估计器的规则提示；previous_strategy（本实验为空）是已完成上一轮策略，两者含义不同。",
        "- 稳定改善仍需新保留集及真实对话评价；不能把同一开发集反复调试后的命中率当作泛化。",
        "- 本批不评估Dialogue回答、语音或数字人观感，不自动启用独立Decision。",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, manifest, checks = validate(args.experiment)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "summary.md").open("x", encoding="utf-8") as file:
        file.write(render(report, manifest, checks))
    write_new(
        args.output / "validation.json",
        {
            "request_boundary_checks": checks,
            "report_sha256": sha(args.experiment / "report.json"),
            "manifest_sha256": sha(args.experiment / "manifest.json"),
            "exporter_sha256": sha(__file__),
            "summary_sha256": sha(args.output / "summary.md"),
            "human_quality_review": "pending",
        },
    )
    print(json.dumps({"request_boundary_checks": checks, "status": "validated"}))


if __name__ == "__main__":
    main()
