"""Offline human review validation and descriptive summaries for frozen E1 bundles."""

import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import re
from statistics import mean

from compare_coordination_models import combined_review, validate_pair
from export_coordination_trace import sha, validate_report

SCORE_FIELDS = ("supportiveness", "coherence", "intent_fit")
EVENT_FIELDS = ("unsupported_diagnosis", "preference_violation")
FIELDS = (*SCORE_FIELDS, *EVENT_FIELDS)
RATING_FIELDS = (*FIELDS, "evidence")


def load_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=nonfinite,
    )


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value
    ):
        raise ValueError(
            "Reviewer/adjudicator ID must be 1-64 ASCII letters, digits, underscores or hyphens"
        )
    if value.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("Reviewer/adjudicator ID cannot be a reserved filename")
    return value


def load_bundle(directory, experiments):
    """Reconstruct every hidden mapping and visible answer from original reports."""
    directory = Path(directory)
    template_path, key_path = (
        directory / "review-blinded-combined.json",
        directory / "review-key.json",
    )
    template, key = load_json(template_path), load_json(key_path)
    hashes = template["source_report_sha256"]
    if not isinstance(hashes, list) or len(set(hashes)) != len(hashes) or not hashes:
        raise ValueError("Invalid report bindings")
    reports, manifests = {}, {}
    for experiment in experiments:
        experiment = Path(experiment)
        for name in ("report.json", "manifest.json", "fixtures.json"):
            if (experiment / name).exists():
                load_json(experiment / name)
        report, manifest = validate_report(experiment)
        digest = sha(experiment / "report.json")
        if digest not in hashes or digest in reports:
            raise ValueError("Unbound or repeated experiment")
        reports[digest], manifests[digest] = report, manifest
    if set(reports) != set(hashes):
        raise ValueError("All bound source reports are required")
    if len(hashes) == 2:
        validate_pair(manifests[hashes[0]], manifests[hashes[1]])
    expected_template, expected_key = combined_review(
        [reports[h] for h in hashes],
        [manifests[h] for h in hashes],
        hashes,
        template["shuffle_seed"],
    )
    if template != expected_template or key != expected_key:
        raise ValueError(
            "Blinded template/key does not match source answers and history"
        )
    lookup = {}
    for digest in hashes:
        for run in reports[digest]["runs"]:
            for row in run["turns"]:
                identity = (
                    digest,
                    run["group"],
                    run["repeat"],
                    run["case_id"],
                    row["turn"],
                )
                if identity in lookup:
                    raise ValueError("Duplicate source identity")
                lookup[identity] = {
                    "model": manifests[digest]["configuration"]["dialogue_model"],
                    "split": run["split"],
                    "category": run["category"],
                    "error": row["error"],
                    "safety_gate": (row["pre_safety"] or {}).get("action")
                    == "escalate",
                }
    metadata = {}
    for item in template["items"]:
        if (
            any(value is not None for value in item["ratings"].values())
            or item["reviewer_id"] is not None
        ):
            raise ValueError("Canonical review template must be blank")
        source = key["items"][item["id"]]
        identity = tuple(
            source[k] for k in ("report_sha256", "group", "repeat", "case_id", "turn")
        )
        metadata[item["id"]] = lookup[identity]
    return {
        "template": template,
        "key": key["items"],
        "metadata": metadata,
        "binding": {
            "template_sha256": sha(template_path),
            "key_sha256": sha(key_path),
            "source_report_sha256": hashes,
        },
    }


def make_form(bundle, reviewer_id):
    identifier(reviewer_id)
    items = copy.deepcopy(bundle["template"]["items"])
    for item in items:
        item["reviewer_id"] = reviewer_id
    # The mapping key and model identities are never included in reviewer forms.
    return {
        "schema_version": 1,
        "template_sha256": bundle["binding"]["template_sha256"],
        "source_report_sha256": bundle["binding"]["source_report_sha256"],
        "reviewer_id": reviewer_id,
        "items": items,
    }


def validate_value(field, value):
    if value is None:
        return
    if field in SCORE_FIELDS:
        if type(value) is not int or not 1 <= value <= 5:
            raise ValueError(f"{field} must be an integer 1-5 or null")
    elif type(value) is not bool:
        raise ValueError(f"{field} must be true, false or null")


def validate_evidence(value, answer):
    if not isinstance(value, dict) or set(value) != {"quote", "note"}:
        raise ValueError("Event evidence needs quote and note")
    if (
        not isinstance(value["quote"], str)
        or not value["quote"].strip()
        or value["quote"] not in answer
    ):
        raise ValueError("Evidence quote must occur verbatim in the final answer")
    if not isinstance(value["note"], str) or not value["note"].strip():
        raise ValueError("Evidence needs a nonblank explanation")


def validate_ratings(ratings, answer):
    if not isinstance(ratings, dict) or set(ratings) != set(RATING_FIELDS):
        raise ValueError("Rating fields must match the review schema exactly")
    for field in FIELDS:
        validate_value(field, ratings[field])
    evidence = ratings["evidence"]
    flagged = {field for field in EVENT_FIELDS if ratings[field] is True}
    if not flagged:
        if evidence is not None:
            raise ValueError("Evidence must be null when no event is marked true")
    else:
        if not isinstance(evidence, dict) or set(evidence) != flagged:
            raise ValueError(
                "Each true event needs its own evidence; no unrelated evidence allowed"
            )
        for value in evidence.values():
            validate_evidence(value, answer)


def validate_form(bundle, form):
    required = {
        "schema_version",
        "template_sha256",
        "source_report_sha256",
        "reviewer_id",
        "items",
    }
    if (
        not isinstance(form, dict)
        or set(form) != required
        or type(form["schema_version"]) is not int
        or form["schema_version"] != 1
    ):
        raise ValueError("Unsupported review form schema")
    reviewer = identifier(form["reviewer_id"])
    for field in ("template_sha256", "source_report_sha256"):
        if form[field] != bundle["binding"][field]:
            raise ValueError("Review form bound to a different template/report")
    expected = {item["id"]: item for item in bundle["template"]["items"]}
    rows = {}
    if not isinstance(form["items"], list):
        raise ValueError("Review items must be a list")
    for item in form["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Each review item needs a string ID")
        identity = item.get("id")
        if identity not in expected or identity in rows:
            raise ValueError("Unknown or duplicate review item")
        original = expected[identity]
        if set(item) != set(original) or any(
            item[k] != original[k]
            for k in original
            if k not in {"ratings", "reviewer_id"}
        ):
            raise ValueError("Only ratings and reviewer identity can change")
        if item["reviewer_id"] != reviewer:
            raise ValueError("Mixed reviewer identities")
        validate_ratings(item["ratings"], item["answer"])
        rows[identity] = item
    if set(rows) != set(expected):
        raise ValueError(
            "Missing review items; retain unanswered items with null ratings"
        )
    return rows


def score_summary(values):
    rated = [v for v in values if v is not None]
    return {
        "rated": len(rated),
        "missing": len(values) - len(rated),
        "mean": round(mean(rated), 4) if rated else None,
        "histogram": {str(i): rated.count(i) for i in range(1, 6)},
    }


def event_summary(values):
    assessed = [v for v in values if v is not None]
    return {
        "assessed": len(assessed),
        "true": sum(v is True for v in values),
        "false": sum(v is False for v in values),
        "missing": len(values) - len(assessed),
        "event_rate": round(sum(assessed) / len(assessed), 4) if assessed else None,
    }


def stratified(bundle, rows, reviewer):
    buckets = defaultdict(list)
    for identity, item in rows.items():
        meta, source = bundle["metadata"][identity], bundle["key"][identity]
        bucket = (
            meta["model"],
            source["group"],
            meta["split"],
            meta["category"],
            meta["safety_gate"],
            bool(meta["error"]),
        )
        buckets[bucket].append(item["ratings"])
    results = []
    for (model, group, split, category, safety_gate, error), ratings in sorted(
        buckets.items()
    ):
        results.append(
            {
                "reviewer_id": reviewer,
                "model": model,
                "group": group,
                "split": split,
                "category": category,
                "safety_gate": safety_gate,
                "flow_error": error,
                "items": len(ratings),
                "scores": {
                    field: score_summary([r[field] for r in ratings])
                    for field in SCORE_FIELDS
                },
                "events": {
                    field: event_summary([r[field] for r in ratings])
                    for field in EVENT_FIELDS
                },
            }
        )
    return results


def paired_scores(bundle, rows, reviewer):
    """Same rater / case / repeat / turn, with faults and local Safety replies excluded."""
    lookup = {}
    models = sorted({meta["model"] for meta in bundle["metadata"].values()})
    groups = sorted({source["group"] for source in bundle["key"].values()})
    for identity, item in rows.items():
        meta, source = bundle["metadata"][identity], bundle["key"][identity]
        if meta["category"] == "fault" or meta["safety_gate"] or meta["error"]:
            continue
        key = (
            meta["model"],
            source["group"],
            source["repeat"],
            source["case_id"],
            source["turn"],
        )
        lookup[key] = item["ratings"]
    comparisons = [
        (model, "R1", model, group, f"R1-{group}")
        for model in models
        for group in groups
        if group != "R1"
    ]
    if len(models) == 2:
        comparisons += [
            (models[0], group, models[1], group, "model_difference") for group in groups
        ]
    result = []
    for left_model, left_group, right_model, right_group, name in comparisons:
        keys = sorted(
            {
                k[2:]
                for k in lookup
                if k[:2] in {(left_model, left_group), (right_model, right_group)}
            }
        )
        for field in SCORE_FIELDS:
            deltas, cases = [], defaultdict(list)
            for repeat, case, turn in keys:
                left = lookup.get((left_model, left_group, repeat, case, turn), {}).get(
                    field
                )
                right = lookup.get(
                    (right_model, right_group, repeat, case, turn), {}
                ).get(field)
                if left is None or right is None:
                    continue
                delta = left - right
                deltas.append(
                    {
                        "repeat": repeat,
                        "case_id": case,
                        "turn": turn,
                        "left": left,
                        "right": right,
                        "difference": delta,
                    }
                )
                cases[case].append(delta)
            case_means = {case: mean(values) for case, values in sorted(cases.items())}
            values = [row["difference"] for row in deltas]
            result.append(
                {
                    "reviewer_id": reviewer,
                    "comparison": name,
                    "left_model": left_model,
                    "left_group": left_group,
                    "right_model": right_model,
                    "right_group": right_group,
                    "field": field,
                    "eligible_pairs": len(keys),
                    "paired_values": len(values),
                    "unpaired_or_unrated": len(keys) - len(values),
                    "mean_difference": round(mean(values), 4) if values else None,
                    "delta_histogram": dict(Counter(str(v) for v in values)),
                    "unique_cases": len(case_means),
                    "case_means": case_means,
                    "case_equal_mean_difference": round(mean(case_means.values()), 4)
                    if case_means
                    else None,
                    "pairs": deltas,
                }
            )
    return result


def agreement_and_consensus(bundle, indices):
    disagreement, consensus, agreement = [], [], {}
    for original in bundle["template"]["items"]:
        identity = original["id"]
        values = [rows[identity]["ratings"] for rows in indices]
        ratings = {field: None for field in RATING_FIELDS}
        evidence = {}
        for field in FIELDS:
            a, b = values[0][field], values[1][field] if len(values) == 2 else None
            if len(values) == 2 and a is not None and b is not None:
                if a == b:
                    ratings[field] = a
                    if field in EVENT_FIELDS and a is True:
                        # Preserve both quotations, not a fabricated merged rationale.
                        evidence[field] = [v["evidence"][field] for v in values]
                else:
                    disagreement.append(
                        {
                            "id": identity,
                            "field": field,
                            "left": a,
                            "right": b,
                            "absolute_difference": abs(a - b)
                            if field in SCORE_FIELDS
                            else None,
                        }
                    )
        ratings["evidence"] = evidence or None
        consensus.append({"id": identity, "ratings": ratings})
    for field in FIELDS:
        pairs = [
            [rows[identity]["ratings"][field] for rows in indices]
            for identity in indices[0]
        ]
        shared, one_missing, both_missing = [], 0, 0
        for pair in pairs:
            values = list(pair)
            if len(values) < 2:
                continue
            a, b = values
            if a is None and b is None:
                both_missing += 1
            elif a is None or b is None:
                one_missing += 1
            else:
                shared.append((a, b))
        matches = sum(a == b for a, b in shared)
        agreement[field] = {
            "both_rated": len(shared),
            "exact_matches": matches,
            "one_missing": one_missing if len(indices) == 2 else None,
            "both_missing": both_missing if len(indices) == 2 else None,
            "exact_agreement": round(matches / len(shared), 4) if shared else None,
            "mean_absolute_difference": round(mean(abs(a - b) for a, b in shared), 4)
            if shared and field in SCORE_FIELDS
            else None,
        }
    return agreement, disagreement, consensus


def adjudication_template(report):
    return {
        "schema_version": 1,
        "template_sha256": report["binding"]["template_sha256"],
        "review_file_sha256": report["review_file_sha256"],
        "adjudicator_id": None,
        "items": [
            {**row, "value": None, "reason": None, "evidence": None}
            for row in report["disagreements"]
        ],
    }


def apply_adjudication(bundle, report, adjudication):
    expected = adjudication_template(report)
    if (
        not isinstance(adjudication, dict)
        or set(adjudication) != set(expected)
        or any(
            adjudication[k] != expected[k]
            for k in expected
            if k not in {"adjudicator_id", "items"}
        )
    ):
        raise ValueError("Adjudication schema/template/review hash mismatch")
    template = {(r["id"], r["field"]): r for r in expected["items"]}
    seen, resolved = set(), 0
    originals = {r["id"]: r for r in bundle["template"]["items"]}
    consensus = {r["id"]: r for r in report["consensus"]}
    if adjudication["adjudicator_id"] is not None:
        identifier(adjudication["adjudicator_id"])
        if adjudication["adjudicator_id"].casefold() in {
            r.casefold() for r in report["reviewer_ids"]
        }:
            raise ValueError("Adjudicator must use a distinct identity")
    if not isinstance(adjudication["items"], list):
        raise ValueError("Adjudication items must be a list")
    for row in adjudication["items"]:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(k), str) for k in ("id", "field")
        ):
            raise ValueError("Each adjudication item needs a string ID and field")
        key = (row.get("id"), row.get("field"))
        if key not in template or key in seen:
            raise ValueError("Unknown or duplicate adjudication item")
        seen.add(key)
        source = template[key]
        if set(row) != set(source) or any(
            row[k] != source[k]
            for k in source
            if k not in {"value", "reason", "evidence"}
        ):
            raise ValueError("Adjudication must preserve original disagreement")
        value, field = row["value"], row["field"]
        validate_value(field, value)
        if value is None:
            if row["reason"] is not None or row["evidence"] is not None:
                raise ValueError("Unresolved adjudication must remain null")
            continue
        if (
            not adjudication["adjudicator_id"]
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise ValueError("Adjudication requires an identity and reason")
        if field in EVENT_FIELDS and value is True:
            validate_evidence(row["evidence"], originals[row["id"]]["answer"])
        elif row["evidence"] is not None:
            raise ValueError("Only true adjudicated events need evidence")
        target = consensus[row["id"]]["ratings"]
        target[field] = value
        if field in EVENT_FIELDS and value is True:
            target["evidence"] = {
                **(target["evidence"] or {}),
                field: [row["evidence"]],
            }
        resolved += 1
    if seen != set(template):
        raise ValueError("Missing adjudication rows; retain null for pending disputes")
    return {
        "resolved": resolved,
        "pending": len(template) - resolved,
        "adjudicator_id": adjudication["adjudicator_id"],
        "decisions": copy.deepcopy(adjudication["items"]),
    }


def summarize(bundle, forms, file_hashes, adjudication=None):
    if not 1 <= len(forms) <= 2 or len(file_hashes) != len(forms):
        raise ValueError("Supply one or two review forms with file hashes")
    indices = [validate_form(bundle, form) for form in forms]
    reviewers = [form["reviewer_id"] for form in forms]
    if len({r.casefold() for r in reviewers}) != len(reviewers) or len(
        set(file_hashes)
    ) != len(file_hashes):
        raise ValueError("Duplicate reviewer identity or file")
    coverage, summaries, paired = [], [], []
    for form, rows in zip(forms, indices):
        counts = {
            field: sum(item["ratings"][field] is not None for item in rows.values())
            for field in FIELDS
        }
        coverage.append(
            {
                "reviewer_id": form["reviewer_id"],
                "items": len(rows),
                "rated_fields": counts,
                "complete_items": sum(
                    all(item["ratings"][f] is not None for f in FIELDS)
                    for item in rows.values()
                ),
                "touched_items": sum(
                    any(item["ratings"][f] is not None for f in FIELDS)
                    for item in rows.values()
                ),
            }
        )
        summaries += stratified(bundle, rows, form["reviewer_id"])
        paired += paired_scores(bundle, rows, form["reviewer_id"])
    agreement, disputes, consensus = agreement_and_consensus(bundle, indices)
    report = {
        "schema_version": 1,
        "binding": bundle["binding"],
        "review_file_sha256": file_hashes,
        "reviewer_ids": reviewers,
        "reviewer_count": len(reviewers),
        "active_reviewers": sum(c["touched_items"] > 0 for c in coverage),
        "coverage": coverage,
        "summaries": summaries,
        "paired": paired,
        "agreement": agreement,
        "disagreements": disputes,
        "consensus": consensus,
        "adjudication": {
            "resolved": 0,
            "pending": len(disputes),
            "adjudicator_id": None,
            "decisions": [],
        },
        "limitations": [
            "Descriptive statistics only; no clinical, significance or automatic winner conclusion",
            "Same synthetic scenarios and repeated generations are correlated; case-equal differences also reported",
            "Scores are ordinal; means supplement the full histograms",
            "Missing/null is not zero, false or agreement; single-reviewer data is labeled",
            "Paired comparisons exclude synthetic faults, input Safety fixed replies and flow errors",
            "Evidence substring checks establish provenance, not correctness of human judgment",
            "Reviewer aliases do not prove two independent people participated",
        ],
        "quality_conclusion": "requires_human_interpretation",
    }
    if adjudication is not None:
        if len(forms) != 2:
            raise ValueError("Adjudication requires two reviewers")
        report["adjudication"] = apply_adjudication(bundle, report, adjudication)
    consensus_rows = {row["id"]: row for row in consensus}
    report["consensus_summaries"] = (
        stratified(bundle, consensus_rows, "consensus") if len(forms) == 2 else []
    )
    report["consensus_paired"] = (
        paired_scores(bundle, consensus_rows, "consensus") if len(forms) == 2 else []
    )
    if not any(c["touched_items"] for c in coverage):
        report["status"] = "pending_review"
    elif any(c["complete_items"] != c["items"] for c in coverage):
        report["status"] = "partial_review"
    elif len(forms) == 1:
        report["status"] = "single_reviewer_complete"
    elif report["adjudication"]["pending"]:
        report["status"] = "pending_adjudication"
    else:
        report["status"] = "two_reviewers_complete"
    return report


def markdown(report):
    lines = [
        "# E2 人工评阅数据检查",
        "",
        f"状态：`{report['status']}`。已提交别名数 {report['reviewer_count']}，实际填写过评分的别名数 {report['active_reviewers']}。",
        "",
        "空值保留为未评，未自动生成质量排名。评分是否合理及裁决是否可信仍需人工判断。",
        "",
        "| 评阅别名 | 条目数 | 填写过 | 五项均完成 |",
        "|---|---:|---:|---:|",
    ]
    for row in report["coverage"]:
        lines.append(
            f"| {row['reviewer_id']} | {row['items']} | {row['touched_items']} | {row['complete_items']} |"
        )
    lines += [
        "",
        "## 双评阅者一致性",
        "",
        "| 字段 | 双方有值 | 一致数 | 完全一致比例 | 单方缺失 |",
        "|---|---:|---:|---|---|",
    ]
    for field, row in report["agreement"].items():
        lines.append(
            f"| {field} | {row['both_rated']} | {row['exact_matches']} | {row['exact_agreement']} | {row['one_missing']} |"
        )
    lines += [
        "",
        f"原始分歧 {len(report['disagreements'])} 项，已裁决 {report['adjudication']['resolved']} 项，仍待裁决 {report['adjudication']['pending']} 项。双方均缺失不会计为一致。",
        "",
        "## 描述性汇总",
        "",
        "| 别名 | 模型/组/分层 | 支持性 n/均值 | 连贯性 n/均值 | 诉求适配 n/均值 |",
        "|---|---|---|---|---|",
    ]
    for row in report["summaries"]:
        scores = [
            f"{row['scores'][field]['rated']}/{row['scores'][field]['mean']}"
            for field in SCORE_FIELDS
        ]
        label = f"{row['model']}/{row['group']}/{row['split']}/{row['category']}/safety={row['safety_gate']}/error={row['flow_error']}"
        lines.append(f"| {row['reviewer_id']} | {label} | {' | '.join(scores)} |")
    lines += [
        "",
        "逐项评分分布、事件的已评/未评数量、成对差值、按案例等权差值和裁决审计见 summary.json。成对比较先匹配同一评阅者/案例/轮次/重复，不把重复输出当独立病例；不合并两位评阅者来扩大样本量。",
        "",
        "## 限制",
        "",
    ]
    lines += ["- " + text for text in report["limitations"]]
    return "\n".join(lines) + "\n"


def prepare(bundle, reviewer_ids, output_dir):
    if not 1 <= len(reviewer_ids) <= 2 or len(
        {r.casefold() for r in reviewer_ids}
    ) != len(reviewer_ids):
        raise ValueError("Choose one or two distinct reviewer aliases")
    forms = [make_form(bundle, reviewer) for reviewer in reviewer_ids]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    for reviewer, form in zip(reviewer_ids, forms):
        write_new_json(output_dir / f"{reviewer}.json", form)


def export_summary(bundle, form_paths, output_dir, adjudication_path=None):
    forms = [load_json(path) for path in form_paths]
    report = summarize(
        bundle,
        forms,
        [sha(path) for path in form_paths],
        load_json(adjudication_path) if adjudication_path else None,
    )
    report["adjudication_file_sha256"] = (
        sha(adjudication_path) if adjudication_path else None
    )
    report["tool_sha256"] = sha(__file__)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_new_json(output_dir / "summary.json", report)
    write_new_json(output_dir / "disagreements.json", adjudication_template(report))
    # No individual review form is rewritten or automatically completed.
    with (output_dir / "summary.md").open("x", encoding="utf-8") as file:
        file.write(markdown(report))
    write_new_json(
        output_dir / "artifacts.json",
        {
            "binding": bundle["binding"],
            "files_sha256": {
                p.name: sha(p) for p in sorted(output_dir.iterdir()) if p.is_file()
            },
        },
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="E1 combined blinded export directory",
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        action="append",
        required=True,
        help="Original experiment directory; repeat for every bound report",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    preparing = sub.add_parser("prepare")
    preparing.add_argument("--reviewer-ids", nargs="+", required=True)
    preparing.add_argument("--output-dir", type=Path, required=True)
    summarizing = sub.add_parser("summarize")
    summarizing.add_argument("--reviews", type=Path, nargs="+", required=True)
    summarizing.add_argument("--adjudication", type=Path)
    summarizing.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(args.bundle, args.experiment)
        if args.command == "prepare":
            prepare(bundle, args.reviewer_ids, args.output_dir)
            print(
                json.dumps(
                    {
                        "created_forms": len(args.reviewer_ids),
                        "items_per_form": len(bundle["template"]["items"]),
                        "ratings": "all_null",
                    }
                )
            )
        else:
            report = export_summary(
                bundle, args.reviews, args.output_dir, args.adjudication
            )
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "active_reviewers": report["active_reviewers"],
                        "disagreements": len(report["disagreements"]),
                    }
                )
            )
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
