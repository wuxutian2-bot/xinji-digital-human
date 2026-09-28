"""Compare saved synthetic evaluations without inventing quality scores."""

import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[1] / "tests/fixtures/mental_health_cases.json"
)


def compare(paths: list[Path], output: Path, fixtures: Path = DEFAULT_FIXTURES) -> None:
    if not paths:
        raise ValueError("At least one report is required")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    reference = reports[0]
    fixture_bytes = fixtures.read_bytes()
    fixture_hash = hashlib.sha256(fixture_bytes).hexdigest()
    fixture_cases = json.loads(fixture_bytes)["cases"]
    fixture_ids = [case["id"] for case in fixture_cases]
    if len(set(fixture_ids)) != len(fixture_ids):
        raise ValueError("Fixture IDs must be unique")
    if any(
        report["provenance"]["fixtures_sha256"] != fixture_hash for report in reports
    ):
        raise ValueError(
            "Reports used different fixtures; rerun with the same fixture version"
        )
    for report in reports:
        ids = [case["id"] for case in report["cases"]]
        if len(ids) != len(fixture_ids) or set(ids) != set(fixture_ids):
            raise ValueError("Each report must contain each fixture case exactly once")
        if report["configuration"].get("safety") != "always_on":
            raise ValueError("Only evaluations with mandatory Safety can be compared")
    lines = [
        "# 心迹模型与消融比较记录",
        "",
        "本报告从已保存的开发评估生成。评分待人工填写，时延仅为本机观察值。",
        "",
        "| 报告 | 对话 | 记忆 | 表达 | 样例数 | 调用错误 | 平均流程秒数 |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for path, report in zip(paths, reports):
        config, metrics = report["configuration"], report["metrics"]
        lines.append(
            f"| {path.stem} | {config['model'] or 'stub'} | {config['memory']} | {config['expression']} | {len(report['cases'])} | {metrics['errors']} | {metrics['latency_mean_seconds']} |"
        )
    same_source = all(
        report["provenance"]["source_sha256"]
        == reference["provenance"]["source_sha256"]
        for report in reports
    )
    generation_keys = ("temperature", "max_tokens", "safety")
    same_generation = all(
        all(
            report["configuration"].get(key) == reference["configuration"].get(key)
            for key in generation_keys
        )
        for report in reports
    )
    personas = [report.get("persona_sha256") for report in reports]
    persona_status = (
        "未记录，无法核对"
        if not all(personas)
        else ("是" if len(set(personas)) == 1 else "否")
    )
    lines += [
        "",
        f"源码哈希完全一致：{'是' if same_source else '否；保留各报告哈希，结果仅作探索性对照'}。",
        f"角色提示词哈希一致：{persona_status}；生成参数一致：{'是' if same_generation else '否'}。",
        "",
        "这些流程包含 Safety 绕过轮次，平均值不等于模型推理时延；须结合各报告运行条件，不能仅凭时延判断模型质量。早期开发轮存在网页并发，不用于严格性能排名。",
        "",
        "## 运行条件与回答完整性",
        "",
    ]
    for path, report in zip(paths, reports):
        completions = [
            item for case in report["cases"] for item in case.get("completions", [])
        ]
        calls = sum(case["dialogue_calls"] for case in report["cases"])
        clipped = sum(item.get("finish_reason") == "length" for item in completions)
        coverage = (
            f"已记录 {len(completions)}/{calls} 次调用，长度截断 {clipped} 次"
            if completions
            else "未记录完成原因，无法核对截断"
        )
        if report["configuration"]["dialogue"] == "stub":
            coverage = "stub 工程模式，不作模型完整性判断"
        lines.append(
            f"- {path.stem}：{report.get('run_note', '早期开发运行，条件未记录')}；{coverage}。"
        )
    lines += [
        "",
        "## Safety 结果",
        "",
        "| 报告 | TP | FP | TN | FN |",
        "|---|---:|---:|---:|---:|",
    ]
    for path, report in zip(paths, reports):
        counts = report["metrics"]["safety_confusion"]
        lines.append(
            f"| {path.stem} | {counts['tp']} | {counts['fp']} | {counts['tn']} | {counts['fn']} |"
        )
    lines += [
        "",
        "标签为开发暂定标签；模糊样例不计入混淆矩阵。相同 Safety 与样例产生相同结果，不是两个对话模型各自安全能力的比较。",
        "",
        "## 长期状态与表达对照",
        "",
    ]
    for path, report in zip(paths, reports):
        cases = {case["id"]: case for case in report["cases"]}
        history = cases.get("history_stress", {})
        strategy = (
            history.get("decisions", [{}])[0]
            .get("strategy", {})
            .get("primary", "未记录")
        )
        if history.get("final_strategies"):
            strategy = history["final_strategies"][0]
        actions = bool(cases.get("ordinary", {}).get("actions", [{}])[0])
        lines.append(
            f"- {path.stem}：压力历史策略 `{strategy}`；普通轮次 Actions 非空：{actions}。"
        )
    lines += [
        "",
        "## 人工质量评阅",
        "",
        "支持性与连贯性各按 1～5 分填写；不当诊断标注有/无并引用具体句子。先逐例阅读，再给出整体结论；未填评分不作优劣排名。",
        "",
    ]
    model_reports = [
        (path, report)
        for path, report in zip(paths, reports)
        if report["configuration"]["dialogue"] == "model"
    ]
    for case in fixture_cases:
        lines += [f"### {case['id']}", ""]
        for turn, prompt in enumerate([case["text"], *case.get("followups", [])], 1):
            lines += [f"输入 {turn}：", ""]
            lines.extend("> " + line for line in prompt.splitlines())
            lines.append("")
        if case.get("history"):
            lines += [
                "虚构历史：`" + json.dumps(case["history"], ensure_ascii=False) + "`。",
                "",
            ]
        for path, report in model_reports:
            row = next(item for item in report["cases"] if item["id"] == case["id"])
            lines += [f"**{path.stem}**（对话调用 {row['dialogue_calls']} 次）", ""]
            for response in row["responses"]:
                lines.extend("> " + line for line in response.splitlines())
                lines.append("")
            lines += ["支持性：待评；连贯性：待评；不当诊断：待评。", ""]
    lines += ["## 源报告与哈希", ""]
    for path, report in zip(paths, reports):
        lines += [
            f"- `{path.as_posix()}`：SHA256 `{hashlib.sha256(path.read_bytes()).hexdigest()}`；生成于 {report['created_at']}。"
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/mental_health_comparison.md")
    )
    args = parser.parse_args()
    compare(args.reports, args.output, args.fixtures)
    print(f"Comparison saved to {args.output}")
