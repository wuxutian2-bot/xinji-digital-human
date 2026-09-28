"""Validate frozen experiments and export factual traces and blinded rating forms."""

import argparse
import hashlib
import json
from pathlib import Path
import random
from statistics import mean, median

from evaluate_coordination import GROUPS, aggregate, make_schedule, write_new_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_report(directory, *, allow_dry_run=False):
    directory = Path(directory)
    report_path, manifest_path = directory / "report.json", directory / "manifest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if report["manifest_sha256"] != sha(manifest_path):
        raise ValueError("Manifest hash mismatch")
    if report["status"] != "complete":
        raise ValueError("Partial/pending run cannot produce a complete comparison")
    if report["dry_run"] != manifest["dry_run"] or (
        report["dry_run"] and not allow_dry_run
    ):
        raise ValueError("Dry run is engineering evidence only")
    if (
        manifest["configuration"]["safety"] != "always_on"
        or manifest["groups"] != GROUPS
    ):
        raise ValueError("Unsupported Safety or ablation configuration")
    if not report["dry_run"] and manifest["repeats"] < 3:
        raise ValueError("Insufficient repeats")
    if manifest["schedule"] != make_schedule(
        manifest["fixtures"]["cases"], manifest["repeats"], manifest["order_seed"]
    ):
        raise ValueError("Schedule is not the complete balanced frozen design")
    expected = [(s["group"], s["repeat"], s["case_id"]) for s in manifest["schedule"]]
    actual = [(r["group"], r["repeat"], r["case_id"]) for r in report["runs"]]
    if expected != actual or len(set(actual)) != len(actual):
        raise ValueError("Missing, repeated or reordered runs")
    fixture_bytes = (directory / "fixtures.json").read_bytes()
    fixture = json.loads(fixture_bytes)
    if fixture != manifest["fixtures"]:
        raise ValueError("Frozen fixture content mismatch")
    # The manifest retains the original source bytes hash; copied JSON may be pretty-printed.
    ids = {case["id"]: case for case in fixture["cases"]}
    for run in report["runs"]:
        case = ids[run["case_id"]]
        if run["category"] != case["category"] or run["split"] != case["split"]:
            raise ValueError("Case classification mismatch")
        if len(run["turns"]) != len(case["turns"]):
            raise ValueError("Missing turns")
        for index, row in enumerate(run["turns"]):
            if row["turn"] != index + 1 or row["input"] != case["turns"][index]["text"]:
                raise ValueError("Mismatched turn/input")
            if not row["error"] and not row["pre_safety"]:
                raise ValueError("Successful turn missing mandatory Safety")
            if row["playback_complete"] is not None:
                raise ValueError("Text-only experiment cannot claim playback")
            if not row["error"] and row["pre_safety"]["action"] != "escalate":
                if not row["post_safety"]:
                    raise ValueError("Successful generated reply missing output Safety")
                if run["group"] == "R3":
                    if (
                        row["trend"] is not None
                        or row["decision_context"]["recent_states"]
                    ):
                        raise ValueError("R3 leaked psychological memory")
                elif row["trend"]["version"] != GROUPS[run["group"]]["trend"]:
                    raise ValueError("Trend ablation mismatch")
                if run["group"] == "R2" and row["intent"]["primary"] != "unknown":
                    raise ValueError("R2 leaked structured intent")
    if aggregate(report["runs"]) != report["metrics"]:
        raise ValueError("Metrics do not match recorded turns")
    return report, manifest


def latency(values):
    if not values:
        return "—"
    ordered = sorted(values)
    # Nearest-rank p95, with a disclosed small sample.
    p95 = ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]
    return f"{mean(values):.3f} / {median(values):.3f} / {p95:.3f}"


def build_summary(report, manifest):
    lines = [
        "# 心迹协同决策对照：自动指标",
        "",
        "工程模式（无真实模型调用）。"
        if report["dry_run"]
        else "真实本机模型实验；人工评分尚未填写，不能据此给出对话质量或临床效果排名。",
        "",
        f"每组 {manifest['repeats']} 次重复；同一虚构样例按固定随机顺序交错；Safety 始终开启。",
        "",
        "| 组 | 正常轮次 | 提议来源：模型/规则/回退/Safety | 策略不符/有标签轮次 | Decision/Dialogue 请求 | 截断 | 输出安全改写 |",
        "|---|---:|---|---|---|---:|---:|",
    ]
    for group, data in report["metrics"].items():
        m = data["ordinary"]
        lines.append(
            f"| {group} | {m['turns']} | {m['model_valid_decisions']}/{m['rules']}/{m['fallbacks']}/{m['safety_gate']} | {m['strategy_mismatches']}/{m['strategy_checked']} | {m['decision_http_attempts']}/{m['dialogue_http_attempts']} | {m['truncated_calls']} | {m['output_safety_overrides']} |"
        )
    lines += [
        "",
        "提议来源按 trace 计数，随后仍经过本机协调；不能把最终策略匹配算成模型提议正确。无标签历史案例保留描述性结果，不计策略准确率。",
        "",
        "## 时延（秒）",
        "",
        "| 组 | 完整轮次均值 / p50 / p95 | Decision 请求均值 / p50 / p95 |",
        "|---|---|---|",
    ]
    for group, data in report["metrics"].items():
        m = data["ordinary"]
        lines.append(
            f"| {group} | {latency(m['full_turn_seconds'])} | {latency(m['decision_request_seconds'])} |"
        )
    lines += [
        "",
        manifest["timing"],
        "",
        "完整轮次包含 Safety 固定回复，不能等同模型时延；p95 使用 nearest-rank。数据量小、未隔离全机所有后台负载，不作吞吐容量结论。",
        "",
        "## 各来源和分层",
        "",
    ]
    for group in GROUPS:
        m, f = report["metrics"][group]["ordinary"], report["metrics"][group]["fault"]
        lines.append(
            f"- {group}：Safety 标签不符 {m['safety_mismatches']}、高风险模型调用 {m['safety_bypass_http_attempts']}；拒绝建议的策略不符 {m['declined_advice_strategy_mismatches']}，文本违背偏好待人工评阅；策略重复 {m['repeated_strategy_count']}/{m['repeat_opportunities']}（不是质量失败数）。合成故障 {f['turns']} 轮，回退 {f['fallbacks']}，流程错误 {f['errors']}，实际 Decision 请求 {f['decision_http_attempts']}。"
        )
        for split in ("development", "holdout"):
            rows = [
                row
                for run in report["runs"]
                if run["group"] == group
                and run["split"] == split
                and run["category"] != "fault"
                for row in run["turns"]
            ]
            lines.append(
                f"  - {split}：有策略标签 {sum(r['strategy_match'] is not None for r in rows)}，不符 {sum(r['strategy_match'] is False for r in rows)}，流程错误 {sum(r['error'] is not None for r in rows)}。"
            )
    lines += [
        "",
        "## 成对分歧（同样例、同轮、同重复）",
        "",
        "| 比较 | 可比较轮次 | 最终策略不同 | 回答不同 |",
        "|---|---:|---:|---:|",
    ]
    keyed = {
        (r["group"], r["repeat"], r["case_id"], t["turn"]): t
        for r in report["runs"]
        if r["category"] != "fault"
        for t in r["turns"]
    }
    for other in ("R0", "R2", "R3", "R4"):
        pairs = [
            (row, keyed[(other, repeat, case, turn)])
            for (group, repeat, case, turn), row in keyed.items()
            if group == "R1"
        ]
        pairs = [(a, b) for a, b in pairs if not a["error"] and not b["error"]]
        lines.append(
            f"| R1 / {other} | {len(pairs)} | {sum(a['final_strategy'] != b['final_strategy'] for a, b in pairs)} | {sum(a['response'] != b['response'] for a, b in pairs)} |"
        )
    lines += [
        "",
        "差异不等于收益。原始模型回答、最终回答、输出改写与能力参数都在 trace.jsonl；评分表覆盖所有组、所有重复和所有轮次，评分初始为空。",
        "",
        "## 失败、覆盖与截断",
        "",
    ]
    issues = 0
    for run in report["runs"]:
        for row in run["turns"]:
            clipped = any(
                call["finish_reason"] == "length" for call in row["api_calls"]
            )
            override = (row["decision_trace"] or {}).get(
                "output_safety_override", False
            )
            if row["error"] or row["strategy_match"] is False or clipped or override:
                issues += 1
                lines.append(
                    f"- {run['group']}/{run['repeat']}/{run['case_id']}/{row['turn']}：error={row['error']}，策略={row['final_strategy']}，预期={row['expected_strategy']}，截断={clipped}，安全改写={override}。"
                )
    if not issues:
        lines.append(
            "- 没有发现流程错误、已标注策略不符、长度截断或输出安全改写；仍须评阅语义质量。"
        )
    lines += ["", "## 限制", ""] + ["- " + line for line in manifest["limitations"]]
    return "\n".join(lines) + "\n"


def export(directory, output_dir, *, allow_dry_run=False, seed=20260923):
    report, manifest = validate_report(directory, allow_dry_run=allow_dry_run)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Choose a new export directory")
    output_dir.mkdir(parents=True)
    report_hash = sha(Path(directory) / "report.json")
    binding = {
        "source_report_sha256": report_hash,
        "manifest_sha256": report["manifest_sha256"],
    }
    traces, review_items, answer_key = [], [], {}
    cases = {c["id"]: c for c in manifest["fixtures"]["cases"]}
    for run in report["runs"]:
        history = []
        for row in run["turns"]:
            identity = {
                key: run[key]
                for key in ("group", "repeat", "case_id", "split", "category")
            }
            traces.append({**binding, **identity, **row})
            review_items.append(
                {
                    "source": {**identity, "turn": row["turn"]},
                    "conversation_before": list(history),
                    "input": row["input"],
                    "answer": row["response"],
                    "synthetic_state_history": cases[run["case_id"]].get("history", []),
                    "ratings": row["human_ratings"],
                    "reviewer_id": None,
                    "note": "Score the final user-visible answer. 1-5 for supportiveness/coherence/intent_fit; event flags require quoted evidence.",
                }
            )
            history.extend(
                [
                    {"role": "user", "text": row["input"]},
                    {"role": "assistant", "text": row["response"]},
                ]
            )
    random.Random(seed).shuffle(review_items)
    for index, item in enumerate(review_items, 1):
        item_id = f"item-{index:04d}"
        answer_key[item_id] = item.pop("source")
        item["id"] = item_id
    with (output_dir / "trace.jsonl").open("x", encoding="utf-8") as file:
        for row in traces:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_new_json(
        output_dir / "review-blinded.json",
        {**binding, "shuffle_seed": seed, "items": review_items},
    )
    write_new_json(output_dir / "review-key.json", {**binding, "items": answer_key})
    with (output_dir / "summary.md").open("x", encoding="utf-8") as file:
        file.write(build_summary(report, manifest))
    write_new_json(
        output_dir / "export-manifest.json",
        {
            **binding,
            "files_sha256": {
                p.name: sha(p) for p in sorted(output_dir.iterdir()) if p.is_file()
            },
        },
    )
    return len(traces)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-dry-run", action="store_true")
    args = parser.parse_args()
    count = export(args.directory, args.output_dir, allow_dry_run=args.allow_dry_run)
    print(json.dumps({"exported_turns": count}))


if __name__ == "__main__":
    main()
