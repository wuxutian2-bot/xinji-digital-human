"""Local-only state management. Does not modify raw chat history."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService  # noqa: E402
from open_llm_vtuber.mental_health.long_term import TrendSettings  # noqa: E402
from open_llm_vtuber.mental_health.schemas import UserStateReport  # noqa: E402


def aware_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use an ISO timestamp with timezone"
        ) from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("A timezone offset is required")
    return parsed.astimezone(timezone.utc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=ROOT / "mental_health_memory/states.sqlite3"
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="Trusted local profile ID; never a character ID",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--history-scope")
    trend = sub.add_parser(
        "trend", help="Read this user's cross-history 7/14-day summary"
    )
    trend.add_argument(
        "--at", type=aware_time, help="ISO timestamp with timezone; default now"
    )
    trend.add_argument(
        "--output", type=Path, help="Create a new JSON file; never overwrite"
    )
    trend.add_argument(
        "--version", choices=["daily_v2", "rolling_v1"], default="daily_v2"
    )
    trend.add_argument(
        "--timezone", default="Asia/Shanghai", help="IANA timezone for daily_v2"
    )
    trend.add_argument("--min-observed-days", type=int, default=3)
    trend.add_argument("--min-topic-days", type=int, default=3)
    trend.add_argument("--stale-after-days", type=int, default=7)
    report = sub.add_parser(
        "self-report",
        help="Store explicit user scores (0..1), separately from estimates",
    )
    report.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSON: timestamp with offset, emotion object, optional topics",
    )
    report.add_argument("--history-scope", required=True)
    correction = sub.add_parser("correct")
    correction.add_argument("--id", required=True)
    correction.add_argument(
        "--changes",
        type=Path,
        required=True,
        help="UTF-8 JSON with emotion/topics/summary/observed_dimensions/interaction_feedback changes",
    )
    deletion = sub.add_parser("delete")
    selection = deletion.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id")
    selection.add_argument("--history-scope")
    selection.add_argument("--all-for-user", action="store_true")
    migration = sub.add_parser("import-jsonl")
    migration.add_argument("--source", type=Path, required=True)
    migration.add_argument(
        "--scope",
        action="append",
        required=True,
        help="Exact legacy scope owned by this user; repeat as needed",
    )
    args = parser.parse_args(argv)
    if args.command == "trend" and not args.database.is_file():
        parser.error("Trend requires an existing database; check --database")
    settings = None
    user_report = None
    try:
        if args.command == "trend":
            settings = TrendSettings(
                version=args.version,
                timezone=args.timezone,
                min_observed_days=args.min_observed_days,
                min_topic_days=args.min_topic_days,
                stale_after_days=args.stale_after_days,
            )
        elif args.command == "self-report":
            user_report = UserStateReport.model_validate_json(
                args.input.read_text(encoding="utf-8")
            )
            if user_report.timestamp > datetime.now(timezone.utc):
                parser.error("Self-report timestamp cannot be in the future")
            if not args.history_scope.strip():
                parser.error("A history scope is required")
    except (ValueError, OSError) as error:
        parser.error(
            f"Invalid input or trend settings ({type(error).__name__}); check schema, scores, timezone and paths"
        )
    store = SqlitePsychologicalMemoryService(
        str(args.database), args.user_id, trend_settings=settings
    )
    if args.command == "trend":
        now = args.at or datetime.now(timezone.utc)
        report = {
            "as_of": now.isoformat(),
            "scope": "configured_user_across_histories",
            "interpretation": "Interaction estimates, not diagnoses; null means unknown",
            "trend": asyncio.run(store.retrieve_trend(now)).model_dump(mode="json"),
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            try:
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(payload + "\n")
            except OSError as error:
                parser.error(
                    f"Cannot create trend output ({type(error).__name__}); choose a new path in an existing directory"
                )
            print(json.dumps({"exported": True}))
        else:
            print(payload)
    elif args.command == "self-report":
        asyncio.run(store.append(args.history_scope, user_report.to_state()))
        print(json.dumps({"stored": True, "source": "user_report"}))
    elif args.command == "list":
        print(
            json.dumps(
                store.list_records(limit=args.limit, history_scope=args.history_scope),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "correct":
        changed = store.correct(
            args.id, json.loads(args.changes.read_text(encoding="utf-8"))
        )
        print(json.dumps({"changed": changed}))
        return 0 if changed else 1
    elif args.command == "delete":
        print(
            json.dumps(
                {
                    "deleted": store.delete(
                        record_id=args.id, history_scope=args.history_scope
                    )
                }
            )
        )
    else:
        print(
            json.dumps({"imported": store.import_jsonl(args.source, set(args.scope))})
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
