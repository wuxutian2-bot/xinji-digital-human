"""Small local JSONL store for structured psychological state records."""

import json
import threading
from asyncio import to_thread
from pathlib import Path
from typing import ClassVar

from loguru import logger

from .schemas import PsychologicalMemoryEntry, PsychologicalState
from .long_term import trend_for_model


class DisabledPsychologicalMemoryService:
    async def append(self, scope, state):
        pass

    async def retrieve_recent(self, scope, limit=None):
        return []


class JsonlPsychologicalMemoryService:
    _locks: ClassVar[dict[Path, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, storage_path: str, recent_limit: int = 5) -> None:
        self.storage_path = Path(storage_path).resolve()
        self.recent_limit = recent_limit
        with self._locks_guard:
            self._file_lock = self._locks.setdefault(
                self.storage_path, threading.Lock()
            )

    async def append(self, scope: str, state: PsychologicalState) -> None:
        entry = PsychologicalMemoryEntry(scope=scope, state=state)
        await to_thread(self._append_locked, entry)

    async def retrieve_recent(
        self, scope: str, limit: int | None = None
    ) -> list[PsychologicalState]:
        return await to_thread(
            self._retrieve_recent_locked,
            scope,
            self.recent_limit if limit is None else limit,
        )

    def _append_locked(self, entry: PsychologicalMemoryEntry) -> None:
        with self._file_lock:
            self._append_sync(entry)

    def _retrieve_recent_locked(
        self, scope: str, limit: int
    ) -> list[PsychologicalState]:
        with self._file_lock:
            return self._retrieve_recent_sync(scope, limit)

    def _append_sync(self, entry: PsychologicalMemoryEntry) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as file:
            file.write(entry.model_dump_json() + "\n")

    def _retrieve_recent_sync(self, scope: str, limit: int) -> list[PsychologicalState]:
        if not self.storage_path.exists():
            return []

        states: list[PsychologicalState] = []
        with self.storage_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    entry = PsychologicalMemoryEntry.model_validate_json(line)
                except (ValueError, json.JSONDecodeError) as error:
                    logger.warning(
                        "Skipping invalid psychological memory line {} ({})",
                        line_number,
                        type(error).__name__,
                    )
                    continue
                if entry.scope == scope:
                    states.append(entry.state)
        return states[-limit:]


def format_memory_context(
    current: PsychologicalState, recent: list[PsychologicalState], trend=None
) -> str:
    """Create compact model context without exposing raw user messages."""
    lines = [
        "The following values are interaction estimates, not diagnoses.",
        "A zero keyword score without an observed dimension is unknown, not evidence of wellbeing.",
        (
            "Current estimate: "
            f"stress={current.emotion.stress:.2f}, "
            f"anxiety={current.emotion.anxiety:.2f}, "
            f"low_mood={current.emotion.low_mood:.2f}, "
            f"risk={current.risk_level.value}, "
            f"strategy={current.interaction_strategy}."
        ),
    ]
    if current.topics:
        lines.append("Current topics: " + ", ".join(current.topics) + ".")
    if recent and getattr(trend, "version", None) != "daily_v2":
        observed = {}
        for dimension in ("stress", "anxiety", "low_mood"):
            values = [
                getattr(item.emotion, dimension)
                for item in recent
                if dimension in item.observed_dimensions
            ]
            observed[dimension] = (
                round(sum(values) / len(values), 3) if values else None
            )
        lines.append(
            "Recent observed estimates (null=unknown): " + json.dumps(observed)
        )
    lines.append(
        "Use this context only to provide supportive, non-diagnostic dialogue."
    )
    if trend is not None:
        lines.append(
            "Time-window summary (null means unknown, not healthy; sources must not be pooled; "
            "only usable history may inform a historical strategy, current Safety takes precedence): "
            + json.dumps(
                trend_for_model(trend.model_dump(mode="json")), ensure_ascii=False
            )
        )
    return "\n".join(lines)
