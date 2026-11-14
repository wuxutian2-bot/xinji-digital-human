"""Explainable, time-bounded summaries of non-diagnostic interaction estimates."""

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from random import Random
from statistics import quantiles
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


class DailyV3Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    half_life_days: float = Field(3.0, ge=0.1, le=365, allow_inf_nan=False)
    bootstrap_samples: int = Field(1000, ge=200, le=5000)
    cusum_k: float = Field(0.03, ge=0, le=1, allow_inf_nan=False)
    cusum_threshold: float = Field(0.35, gt=0, le=10, allow_inf_nan=False)
    cusum_min_run_days: int = Field(3, ge=2, le=7)


class TrendSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["rolling_v1", "daily_v2", "daily_v3"] = "rolling_v1"
    daily_v3: DailyV3Settings | None = Field(
        None, exclude_if=lambda value: value is None
    )
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


class DailyDimensionV3(DailyDimension):
    weighted_mean: float | None = None
    weighted_change: float | None = None
    interval80: tuple[float, float] | None = None
    daily_smoothed: dict[str, float] = Field(default_factory=dict)
    daily_intervals: dict[str, tuple[float, float]] = Field(default_factory=dict)
    alert: Literal["rising"] | None = None
    alert_started_at: str | None = None
    source_disagreement: bool = False
    disagreement_days: list[str] = Field(default_factory=list)


class DailySourceV3(DailySource):
    dimensions: dict[str, DailyDimensionV3] = Field(default_factory=dict)


class DailyStateTrendV3(DailyStateTrend):
    version: Literal["daily_v3"] = "daily_v3"
    primary_source: Literal["per_dimension"] = "per_dimension"
    sources: dict[str, DailySourceV3] = Field(default_factory=dict)
    preferred_sources: dict[str, str | None] = Field(default_factory=dict)
    source_disagreement: dict[str, list[str]] = Field(default_factory=dict)


def observation_source(state: PsychologicalState) -> str:
    return {
        "keyword_v1": "system_estimate",
        "context_v2": "system_estimate",
        "llm_v1": "system_estimate",
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


def weighted_daily_summary(
    points: dict[str, float],
    reference: date,
    options: DailyV3Settings,
    minimum_days: int,
) -> tuple[float | None, tuple[float, float] | None]:
    if not points:
        return None, None
    pairs = [
        (
            value,
            2 ** (-(reference - date.fromisoformat(day)).days / options.half_life_days),
        )
        for day, value in sorted(points.items())
    ]

    def average(sample):
        return sum(value * weight for value, weight in sample) / sum(
            weight for _, weight in sample
        )

    value = round(average(pairs), 6)
    if len(pairs) < max(3, minimum_days):
        return value, None
    # Resample daily observations with their calendar-age weights. Every call has
    # a local deterministic RNG, so ordering, exact replays and concurrent users
    # cannot change the interval.
    rng = Random(0)
    samples = [
        average(rng.choices(pairs, k=len(pairs)))
        for _ in range(options.bootstrap_samples)
    ]
    bounds = quantiles(samples, n=10, method="inclusive")
    return value, (round(bounds[0], 6), round(bounds[8], 6))


def rising_alert(
    metric: DailyDimensionV3, options: DailyV3Settings, minimum_days: int
) -> str | None:
    if not metric.eligible_for_decision or metric.previous_observed_days < max(
        3, minimum_days
    ):
        return None
    baseline = sum(metric.previous_daily_means.values()) / metric.previous_observed_days
    total, run = 0.0, 0
    start, previous = None, None
    for day, value in sorted(metric.daily_means.items()):
        current = date.fromisoformat(day)
        if previous is not None and (current - previous).days != 1:
            total, run, start = 0.0, 0, None
        increment = value - baseline - options.cusum_k
        if total == 0 and increment > 0:
            start = day
        total = max(0.0, total + increment)
        run = run + 1 if increment > 0 else 0
        if total == 0:
            start = None
        previous = current
    if total > options.cusum_threshold and run >= options.cusum_min_run_days:
        return start
    return None


def summarize_daily_trend_v3(
    states: Iterable[PsychologicalState],
    now: datetime | None = None,
    settings: TrendSettings | None = None,
) -> DailyStateTrendV3:
    settings = settings or TrendSettings(version="daily_v3")
    if settings.version != "daily_v3":
        raise ValueError("daily_v3 settings required")
    options = settings.daily_v3 or DailyV3Settings()
    # Keep the frozen v2 aggregator's date, provenance, duplicate and stale rules.
    base = summarize_daily_trend(
        states,
        now,
        settings.model_copy(update={"version": "daily_v2", "daily_v3": None}),
    )
    result = DailyStateTrendV3.model_validate(
        {
            **base.model_dump(),
            "version": "daily_v3",
            "settings": settings,
            "primary_source": "per_dimension",
        }
    )
    today = result.as_of.astimezone(ZoneInfo(settings.timezone)).date()
    for source in result.sources.values():
        for metric in source.dimensions.values():
            metric.weighted_mean, metric.interval80 = weighted_daily_summary(
                metric.daily_means, today, options, settings.min_observed_days
            )
            prior, _ = weighted_daily_summary(
                metric.previous_daily_means,
                today - timedelta(days=7),
                options,
                settings.min_observed_days,
            )
            if metric.change is not None:
                metric.weighted_change = round(metric.weighted_mean - prior, 6)
            points = {**metric.previous_daily_means, **metric.daily_means}
            for day in sorted(points):
                current = date.fromisoformat(day)
                window = {
                    d: score
                    for d, score in points.items()
                    if 0 <= (current - date.fromisoformat(d)).days <= 6
                }
                value, interval = weighted_daily_summary(
                    window, current, options, settings.min_observed_days
                )
                metric.daily_smoothed[day] = value
                if interval is not None:
                    metric.daily_intervals[day] = interval
            metric.alert_started_at = rising_alert(
                metric, options, settings.min_observed_days
            )
            metric.alert = "rising" if metric.alert_started_at is not None else None
    for dim in DIMENSIONS:
        system = result.sources["system_estimate"].dimensions[dim]
        report = result.sources["user_report"].dimensions[dim]
        disagreement = [
            day
            for day in sorted(system.daily_means.keys() & report.daily_means.keys())
            if round(abs(system.daily_means[day] - report.daily_means[day]), 6) > 0.3
        ]
        result.source_disagreement[dim] = disagreement
        for metric in (system, report):
            metric.disagreement_days = list(disagreement)
            metric.source_disagreement = bool(disagreement)
        preferred = (
            "user_report"
            if disagreement
            else next(
                (
                    source
                    for source in ("system_estimate", "user_report", "user_correction")
                    if result.sources[source].dimensions[dim].eligible_for_decision
                ),
                None,
            )
        )
        result.preferred_sources[dim] = preferred
        metric = result.sources[preferred].dimensions[dim] if preferred else None
        result.means[dim] = (
            metric.weighted_mean if metric and metric.eligible_for_decision else None
        )
        result.changes[dim] = (
            metric.weighted_change if metric and metric.eligible_for_decision else None
        )
    result.insufficient_data = all(value is None for value in result.means.values())
    return result


def trend_for_model(trend: dict) -> dict:
    """Compact, source-separated evidence; withheld scores cannot drive decisions."""
    if trend.get("version") == "daily_v3":
        return trend_v3_for_model(trend)
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


def trend_v3_for_model(trend: dict) -> dict:
    if "decision_dimensions" in trend:
        return trend
    result = trend_for_model({**trend, "version": "daily_v2"})
    result.update(
        version="daily_v3",
        preferred_sources=trend["preferred_sources"],
        source_disagreement=trend["source_disagreement"],
        decision_dimensions={},
    )
    for dim in DIMENSIONS:
        preferred = trend["preferred_sources"][dim]
        selected = None
        for source in SOURCES:
            metric = trend["sources"][source]["dimensions"][dim]
            projected = result["sources"][source][dim]
            usable = source == preferred and metric["eligible_for_decision"]
            projected.update(
                mean=metric["weighted_mean"] if usable else None,
                change=metric["weighted_change"] if usable else None,
                interval80=metric["interval80"] if usable else None,
                alert=metric["alert"] if usable else None,
                alert_started_at=metric["alert_started_at"] if usable else None,
                status="usable"
                if usable
                else "deferred"
                if source != preferred and preferred
                else projected["status"],
            )
            if source == preferred:
                selected = {**projected, "source": preferred}
        result["decision_dimensions"][dim] = selected or {
            "source": None,
            "status": "insufficient",
            "mean": None,
            "change": None,
            "interval80": None,
            "alert": None,
            "alert_started_at": None,
        }
    return result
