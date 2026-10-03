"""Prepare blank adult-trial records and summarize actual observations, never infer outcomes."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("倾诉", "切换求助", "纠正记录", "保存行动", "打断并恢复")
RATINGS = ("被理解感", "偏好被尊重", "记忆控制感")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Task(Strict):
    result: Literal["independent", "assisted", "failed"] | None = None
    duration_seconds: float | None = Field(None, ge=0, le=86400, allow_inf_nan=False)
    failure_reason: str | None = Field(None, max_length=500)


class Participant(Strict):
    id: str = Field(pattern=r"^P[0-9]{2,3}$")
    invited: bool = True
    adult_confirmed: bool = False
    consent: bool = False
    visited: bool = False
    interview_quote: str | None = Field(None, max_length=2000)
    need_category: str | None = Field(None, max_length=100)
    feature: str | None = Field(None, max_length=100)
    verification_note: str | None = Field(None, max_length=1000)
    tasks: dict[str, Task] = Field(
        default_factory=lambda: {name: Task() for name in TASKS}
    )
    ratings: dict[str, StrictInt | None] = Field(
        default_factory=lambda: {name: None for name in RATINGS}
    )
    negative_feedback: str | None = Field(None, max_length=2000)
    return_invited: bool = False
    returned: bool = False
    action_count: int | None = Field(None, ge=0, strict=True)
    action_helpful: int | None = Field(None, ge=0, strict=True)
    action_unhelpful: int | None = Field(None, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent(self):
        if set(self.tasks) != set(TASKS) or set(self.ratings) != set(RATINGS):
            raise ValueError(
                "Keep the same task and rating questions for every participant"
            )
        if any(
            value is not None and (type(value) is not int or not 1 <= value <= 5)
            for value in self.ratings.values()
        ):
            raise ValueError("Ratings must be integers 1..5 or null")
        if (self.visited or self.interview_quote) and not (
            self.adult_confirmed and self.consent
        ):
            raise ValueError(
                "Record participation only after adult confirmation and consent"
            )
        if self.returned and not (self.visited and self.return_invited):
            raise ValueError(
                "A recorded return requires an initial visit and return invitation"
            )
        observed = any(v.result is not None for v in self.tasks.values()) or any(
            v is not None for v in self.ratings.values()
        )
        if observed and not self.visited:
            raise ValueError("Do not fill outcomes for people who have not visited")
        if self.action_helpful is not None or self.action_unhelpful is not None:
            if (
                self.action_count is None
                or (self.action_helpful or 0) + (self.action_unhelpful or 0)
                > self.action_count
            ):
                raise ValueError("Action feedback cannot exceed recorded actions")
        return self


class Study(Strict):
    schema_version: Literal[1] = 1
    synthetic: Literal[False] = False
    version: str = Field(min_length=1, max_length=100)
    participants: list[Participant]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [p.id for p in self.participants]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate participant IDs")
        return self


def summarize(study):
    actual = [p for p in study.participants if p.visited]
    result = {
        "version": study.version,
        "synthetic": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "invited": sum(p.invited for p in study.participants),
        "visited": len(actual),
        "interviewed": sum(bool(p.interview_quote) for p in study.participants),
        "return_invited": sum(p.return_invited for p in actual),
        "returned": sum(p.returned for p in actual),
        "negative_feedback_count": sum(bool(p.negative_feedback) for p in actual),
        "tasks": {},
        "ratings": {},
        "limits": "Prototype usability and subjective experience only; no clinical efficacy or causal improvement claim.",
    }
    for name in TASKS:
        data = [p.tasks[name] for p in actual]
        attempted = [t for t in data if t.result is not None]
        durations = [
            t.duration_seconds for t in attempted if t.duration_seconds is not None
        ]
        result["tasks"][name] = {
            "attempted": len(attempted),
            "missing": len(data) - len(attempted),
            **{
                state: sum(t.result == state for t in attempted)
                for state in ("independent", "assisted", "failed")
            },
            "duration_n": len(durations),
            "mean_seconds": round(sum(durations) / len(durations), 2)
            if durations
            else None,
        }
    for name in RATINGS:
        values = [p.ratings[name] for p in actual if p.ratings[name] is not None]
        result["ratings"][name] = {
            "n": len(values),
            "missing": len(actual) - len(values),
            "mean": round(sum(values) / len(values), 2) if values else None,
            "low_1_or_2": sum(v <= 2 for v in values),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "summarize"])
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--version", default="companion-2026-10-01")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.file.resolve()
    if (ROOT / "private" / "trials").resolve() not in target.parents:
        parser.error("Raw observations must stay under private/trials")
    if args.command == "prepare":
        if not 8 <= args.count <= 15:
            parser.error("This protocol supports 8..15 invited adult classmates")
        target.parent.mkdir(parents=True, exist_ok=True)
        study = Study(
            version=args.version,
            participants=[Participant(id=f"P{i:02}") for i in range(1, args.count + 1)],
        )
        with target.open("x", encoding="utf-8") as stream:
            stream.write(study.model_dump_json(indent=2))
        print(
            f"Blank records created: {target}; no participant results have been entered."
        )
    else:
        result = summarize(
            Study.model_validate_json(target.read_text(encoding="utf-8"))
        )
        if not args.output:
            parser.error("Specify a new --output JSON file for the aggregate report")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(f"Actual visits: {result['visited']}; aggregate report: {args.output}")


if __name__ == "__main__":
    main()
