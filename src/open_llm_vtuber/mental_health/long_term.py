"""Explainable, time-bounded summaries of non-diagnostic interaction estimates."""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schemas import PsychologicalState


class StateTrend(BaseModel):
    version: Literal["rolling_v1"] = "rolling_v1"
    window_days: int = 7
    sample_count: int = 0
    previous_sample_count: int = 0
    observed_counts: dict[str, int] = Field(default_factory=dict)
    means: dict[str, float | None] = Field(default_factory=dict)
    changes: dict[str, float | None] = Field(default_factory=dict)
    recurring_topics: list[str] = Field(default_factory=list)
    insufficient_data: bool = True


def summarize_trend(
    states: list[PsychologicalState], now: datetime | None = None
) -> StateTrend:
    now = now or datetime.now(timezone.utc)
    recent, previous = [], []
    for state in states:
        timestamp = state.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age = now - timestamp
        if timedelta(0) <= age <= timedelta(days=7):
            recent.append(state)
        elif timedelta(days=7) < age <= timedelta(days=14):
            previous.append(state)
    result = StateTrend(sample_count=len(recent), previous_sample_count=len(previous))
    for dimension in ("stress", "anxiety", "low_mood"):
        current = [
            getattr(s.emotion, dimension)
            for s in recent
            if dimension in s.observed_dimensions
        ]
        prior = [
            getattr(s.emotion, dimension)
            for s in previous
            if dimension in s.observed_dimensions
        ]
        result.observed_counts[dimension] = len(current)
        result.means[dimension] = (
            round(sum(current) / len(current), 3) if current else None
        )
        result.changes[dimension] = (
            round(sum(current) / len(current) - sum(prior) / len(prior), 3)
            if len(current) >= 3 and len(prior) >= 3
            else None
        )
    result.insufficient_data = max(result.observed_counts.values(), default=0) < 3
    counts = Counter(topic for state in recent for topic in set(state.topics))
    result.recurring_topics = sorted(
        topic for topic, count in counts.items() if count >= 3
    )
    return result


DIMENSIONS = ("stress", "anxiety", "low_mood")
SOURCES = ("system_estimate", "user_report", "user_correction")


class TrendSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["rolling_v1", "daily_v2"] = "rolling_v1"
    timezone: str = "Asia/Shanghai"
    min_observed_days: int = Field(3, ge=1, le=7)
    min_topic_days: int = Field(3, ge=1, le=7)
    stale_after_days: int = Field(7, ge=0, le=365)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("An installed IANA timezone is required") from error
        return value


class CalendarWindow(BaseModel):
    start: datetime
    end_exclusive: datetime


class DailyDimension(BaseModel):
    mean: float | None = None
    previous_mean: float | None = None
    change: float | None = None
    observed_days: int = 0
    previous_observed_days: int = 0
    coverage: float = 0
    previous_coverage: float = 0
    last_observed_at: datetime | None = None
    age_days: int | None = None
    stale: bool = False
    eligible_for_decision: bool = False
    daily_means: dict[str, float] = Field(default_factory=dict)
    previous_daily_means: dict[str, float] = Field(default_factory=dict)


class DailySource(BaseModel):
    dimensions: dict[str, DailyDimension] = Field(default_factory=dict)
    topic_observed_days: dict[str, int] = Field(default_factory=dict)
    topic_age_days: dict[str, int] = Field(default_factory=dict)
    recurring_topics: list[str] = Field(default_factory=list)


class DailyStateTrend(BaseModel):
    version: Literal["daily_v2"] = "daily_v2"
    settings: TrendSettings
    as_of: datetime
    current_window: CalendarWindow
    previous_window: CalendarWindow
    primary_source: Literal["system_estimate"] = "system_estimate"
    sample_count: int = 0  # Raw rows, diagnostic only; never an evidence threshold.
    previous_sample_count: int = 0
    excluded_records: dict[str, int] = Field(default_factory=dict)
    sources: dict[str, DailySource] = Field(default_factory=dict)
    # Compatibility display fields contain system estimates only, never pooled scores.
    means: dict[str, float | None] = Field(default_factory=dict)
    changes: dict[str, float | None] = Field(default_factory=dict)
    recurring_topics: list[str] = Field(default_factory=list)
    insufficient_data: bool = True


def observation_source(state: PsychologicalState) -> str:
    return {
        "keyword_v1": "system_estimate",
        "context_v2": "system_estimate",
        "user_report": "user_report",
        "user_correction": "user_correction",
    }.get(state.estimator_source, "unknown")


def summarize_daily_trend(
    states: Iterable[PsychologicalState],
    now: datetime | None = None,
    settings: TrendSettings | None = None,
) -> DailyStateTrend:
    settings = settings or TrendSettings(version="daily_v2")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Reference time requires a timezone")
    if settings.version != "daily_v2":
        raise ValueError("daily_v2 settings required")
    zone = ZoneInfo(settings.timezone)
    today = now.astimezone(zone).date()
    start_day, previous_day = today - timedelta(days=6), today - timedelta(days=13)
    result = DailyStateTrend(
        settings=settings,
        as_of=now,
        current_window=CalendarWindow(
            start=datetime.combine(start_day, time.min, zone),
            end_exclusive=datetime.combine(today + timedelta(days=1), time.min, zone),
        ),
        previous_window=CalendarWindow(
            start=datetime.combine(previous_day, time.min, zone),
            end_exclusive=datetime.combine(start_day, time.min, zone),
        ),
        excluded_records={"unknown_time": 0, "unknown_source": 0, "future": 0},
    )
    # Exact timestamp/value replays contribute once to each source/dimension/day.
    # Distinct observations on that day are averaged, then days receive equal weight.
    values = defaultdict(lambda: defaultdict(set))
    last = {}
    topics = defaultdict(lambda: defaultdict(set))
    for state in states:
        stamp = state.timestamp
        if (
            not state.timestamp_known
            or stamp.tzinfo is None
            or stamp.utcoffset() is None
        ):
            result.excluded_records["unknown_time"] += 1
            continue
        stamp = stamp.astimezone(timezone.utc)
        if stamp > now.astimezone(timezone.utc):
            result.excluded_records["future"] += 1
            continue
        day = stamp.astimezone(zone).date()
        source = observation_source(state)
        topic_source = state.topics_source or source
        dimension_sources = {
            dim: state.dimension_sources.get(dim, source)
            for dim in state.observed_dimensions
        }
        if topic_source not in SOURCES and not any(
            s in SOURCES for s in dimension_sources.values()
        ):
            result.excluded_records["unknown_source"] += 1
            continue
        if day >= start_day:
            result.sample_count += 1
        elif day >= previous_day:
            result.previous_sample_count += 1
        for dim, origin in dimension_sources.items():
            if origin not in SOURCES:
                continue
            key = origin, dim
            if key not in last or stamp > last[key]:
                last[key] = stamp
            if day >= previous_day:
                values[key][day].add((stamp, getattr(state.emotion, dim)))
        if day >= start_day and topic_source in SOURCES:
            for topic in set(state.topics):
                topics[topic_source][topic].add(day)

    def average(numbers):
        return sum(numbers) / len(numbers) if numbers else None

    for source in SOURCES:
        source_result = DailySource()
        for dim in DIMENSIONS:
            raw = {
                day: average([score for _, score in items])
                for day, items in values[source, dim].items()
            }
            current = {
                str(day): mean for day, mean in sorted(raw.items()) if day >= start_day
            }
            previous = {
                str(day): mean for day, mean in sorted(raw.items()) if day < start_day
            }
            mean, prior = (
                average(list(current.values())),
                average(list(previous.values())),
            )
            last_at = last.get((source, dim))
            age = (today - last_at.astimezone(zone).date()).days if last_at else None
            stale = age is not None and age > settings.stale_after_days
            metric = DailyDimension(
                mean=round(mean, 3) if mean is not None else None,
                previous_mean=round(prior, 3) if prior is not None else None,
                change=round(mean - prior, 3)
                if len(current) >= settings.min_observed_days
                and len(previous) >= settings.min_observed_days
                else None,
                observed_days=len(current),
                previous_observed_days=len(previous),
                coverage=round(len(current) / 7, 3),
                previous_coverage=round(len(previous) / 7, 3),
                last_observed_at=last_at,
                age_days=age,
                stale=stale,
                eligible_for_decision=len(current) >= settings.min_observed_days
                and not stale,
                daily_means={day: round(value, 3) for day, value in current.items()},
                previous_daily_means={
                    day: round(value, 3) for day, value in previous.items()
                },
            )
            source_result.dimensions[dim] = metric
        source_result.topic_observed_days = {
            topic: len(days) for topic, days in sorted(topics[source].items())
        }
        source_result.recurring_topics = [
            topic
            for topic, count in source_result.topic_observed_days.items()
            if count >= settings.min_topic_days
        ]
        source_result.topic_age_days = {
            topic: (today - max(days)).days
            for topic, days in sorted(topics[source].items())
        }
        result.sources[source] = source_result
    primary = result.sources["system_estimate"]
    result.means = {dim: metric.mean for dim, metric in primary.dimensions.items()}
    result.changes = {dim: metric.change for dim, metric in primary.dimensions.items()}
    result.recurring_topics = primary.recurring_topics
    result.insufficient_data = not any(
        metric.eligible_for_decision
        for source in result.sources.values()
        for metric in source.dimensions.values()
    )
    return result


def trend_for_model(trend: dict) -> dict:
    """Compact, source-separated evidence; withheld scores cannot drive decisions."""
    if trend.get("version") != "daily_v2":
        return trend
    sources = {}
    for source, data in trend.get("sources", {}).items():
        sources[source] = {}
        for dim, metric in data["dimensions"].items():
            eligible = metric["eligible_for_decision"]
            sources[source][dim] = {
                "mean": metric["mean"] if eligible else None,
                "change": metric["change"] if eligible else None,
                "observed_days": metric["observed_days"],
                "coverage": metric["coverage"],
                "age_days": metric["age_days"],
                "status": "usable"
                if eligible
                else "stale"
                if metric["stale"]
                else "insufficient",
            }
    return {
        "version": "daily_v2",
        "as_of": trend["as_of"],
        "settings": trend["settings"],
        "current_window": trend["current_window"],
        "previous_window": trend["previous_window"],
        "sources": sources,
        "recurring_topics": {
            source: [
                topic
                for topic in data["recurring_topics"]
                if data["topic_age_days"][topic]
                <= trend["settings"]["stale_after_days"]
            ]
            for source, data in trend["sources"].items()
        },
        "insufficient_data": trend["insufficient_data"],
    }
