"""Compare two frozen coordination experiments only when shared controls match."""

import argparse
import json
from pathlib import Path
import random

from export_coordination_trace import sha, validate_report
from evaluate_coordination import GROUPS, write_new_json


def validate_pair(left, right):
    if (
        left["configuration"]["dialogue_model"]
        == right["configuration"]["dialogue_model"]
    ):
        raise ValueError("Two distinct Dialogue models are required")
    for field in (
        "persona_sha256",
        "groups",
        "repeats",
        "order_seed",
        "schedule",
        "fixtures",
        "as_of",
    ):
        if left[field] != right[field]:
            raise ValueError(f"Different experiment control: {field}")
    for field in ("source_sha256", "fixtures_sha256"):
        if left["provenance"][field] != right["provenance"][field]:
            raise ValueError(f"Different frozen provenance: {field}")
    left_config = {
        k: v for k, v in left["configuration"].items() if k != "dialogue_model"
    }
    right_config = {
        k: v for k, v in right["configuration"].items() if k != "dialogue_model"
    }
    if left_config != right_config:
        raise ValueError("Generation, Safety or statistics controls differ")
    common_names = {
        name
        for name in left["model_artifacts"]
        if name.startswith(("decision_", "base_"))
    }
    if common_names != {
        name
        for name in right["model_artifacts"]
        if name.startswith(("decision_", "base_"))
    }:
        raise ValueError("Shared artifact inventory differs")
    for name in common_names:
        if left["model_artifacts"][name] != right["model_artifacts"][name]:
            raise ValueError("Decision/base model artifacts differ")


def combined_review(reports, manifests, report_hashes, seed):
    items, key = [], {}
    for report, manifest, report_hash in zip(reports, manifests, report_hashes):
        cases = {case["id"]: case for case in manifest["fixtures"]["cases"]}
        for run in report["runs"]:
            conversation = []
            for row in run["turns"]:
                items.append(
                    {
                        "_source": {
                            "report_sha256": report_hash,
                            "group": run["group"],
                            "repeat": run["repeat"],
                            "case_id": run["case_id"],
                            "turn": row["turn"],
                        },
                        "input": row["input"],
                        "answer": row["response"],
                        "conversation_before": list(conversation),
                        "synthetic_state_history": cases[run["case_id"]].get(
                            "history", []
                        ),
                        "ratings": row["human_ratings"],
                        "reviewer_id": None,
                    }
                )
                conversation.extend(
                    [
                        {"role": "user", "text": row["input"]},
                        {"role": "assistant", "text": row["response"]},
                    ]
                )
    random.Random(seed).shuffle(items)
    for number, item in enumerate(items, 1):
        identity = f"item-{number:04d}"
        key[identity] = item.pop("_source")
        item["id"] = identity
    return {
        "source_report_sha256": report_hashes,
        "shuffle_seed": seed,
        "items": items,
    }, {"source_report_sha256": report_hashes, "items": key}


def compare(left_dir, right_dir, output_dir):
    left_report, left = validate_report(left_dir)
    right_report, right = validate_report(right_dir)
    validate_pair(left, right)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Choose a new comparison directory")
    output_dir.mkdir(parents=True)
    models = [m["configuration"]["dialogue_model"] for m in (left, right)]
    paired = []
    for group in GROUPS:

        def rows(report):
            return {
                (r["repeat"], r["case_id"], t["turn"]): t
                for r in report["runs"]
                if r["group"] == group and r["category"] != "fault"
                for t in r["turns"]
            }

        a, b = rows(left_report), rows(right_report)
        if set(a) != set(b):
            raise ValueError("Unpaired turns")
        valid = [
            (a[key], b[key]) for key in a if not a[key]["error"] and not b[key]["error"]
        ]
        paired.append(
            {
                "group": group,
                "paired_turns": len(valid),
                "strategy_disagreements": sum(
                    x["final_strategy"] != y["final_strategy"] for x, y in valid
                ),
                "reply_disagreements": sum(
                    x["response"] != y["response"] for x, y in valid
                ),
                "supportiveness_difference": None,
                "coherence_difference": None,
                "intent_fit_difference": None,
            }
        )
    binding = {
        "source_report_sha256": [
            sha(Path(d) / "report.json") for d in (left_dir, right_dir)
        ],
        "manifest_sha256": [
            sha(Path(d) / "manifest.json") for d in (left_dir, right_dir)
        ],
        "comparison_script_sha256": sha(__file__),
        "models": models,
        "shared_controls_match": True,
        "paired": paired,
        "quality_conclusion": "pending_human_review",
        "limitation": "Sequential local runs, not simultaneous randomized model assignment; model-specific service runtime and load may differ.",
    }
    write_new_json(output_dir / "comparison.json", binding)
    review, key = combined_review(
        (left_report, right_report),
        (left, right),
        binding["source_report_sha256"],
        left["order_seed"],
    )
    write_new_json(output_dir / "review-blinded-combined.json", review)
    write_new_json(output_dir / "review-key.json", key)
    lines = [
        "# ORPO / SFT 协同实验复查",
        "",
        "源码、样例、角色提示词、调度、生成控制、Safety、Decision 权重和基座权重一致；仅 Dialogue 适配器/模型变化。人工质量分数为空，差异不等于收益。",
        "",
        "| 模型 | 组 | 正常轮次 | 策略不符/检查数 | 实际 Decision/Dialogue | 流程错误 | 截断 |",
        "|---|---|---:|---|---|---:|---:|",
    ]
    for model, report in zip(models, (left_report, right_report)):
        for group, metrics in report["metrics"].items():
            m = metrics["ordinary"]
            lines.append(
                f"| {model} | {group} | {m['turns']} | {m['strategy_mismatches']}/{m['strategy_checked']} | {m['decision_http_attempts']}/{m['dialogue_http_attempts']} | {m['errors']} | {m['truncated_calls']} |"
            )
    lines += [
        "",
        "## 同条件的成对差异",
        "",
        "| 组 | 对齐轮次 | 最终策略不同 | 回答不同 |",
        "|---|---:|---:|---:|",
    ]
    for row in paired:
        lines.append(
            f"| {row['group']} | {row['paired_turns']} | {row['strategy_disagreements']} | {row['reply_disagreements']} |"
        )
    lines += [
        "",
        "这是顺序运行的第二轮泛化复查；未消除全机负载和服务运行状态差异。不能将完整轮次时间直接用于模型速度排名，不能将小型虚构数据上的匹配率解释为临床有效性。",
        "",
        "合成故障、高风险模型绕过、输出改写、逐次重复以及原始回答详见各实验 summary.md / trace.jsonl。匿名评分表分别绑定原报告哈希，评阅结束前不作支持性、连贯性或诉求适配的优劣结论。",
    ]
    with (output_dir / "comparison.md").open("x", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    write_new_json(
        output_dir / "comparison-artifacts.json",
        {
            "source_report_sha256": binding["source_report_sha256"],
            "files_sha256": {
                path.name: sha(path)
                for path in sorted(output_dir.iterdir())
                if path.is_file()
            },
        },
    )
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.left, args.right, args.output_dir)
    print(json.dumps({"shared_controls_match": result["shared_controls_match"]}))


if __name__ == "__main__":
    main()
