"""User-bound SQLite state storage. Caller supplies a trusted server-side user ID."""

from asyncio import to_thread
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .long_term import (
    DailyStateTrend,
    StateTrend,
    TrendSettings,
    observation_source,
    summarize_daily_trend,
    summarize_trend,
)
from .schemas import InteractionIntent, PsychologicalMemoryEntry, PsychologicalState


class SqlitePsychologicalMemoryService:
    def __init__(
        self,
        storage_path: str,
        user_id: str,
        recent_limit: int = 5,
        *,
        trend_settings: TrendSettings | dict | None = None,
    ):
        if not user_id.strip():
            raise ValueError("A trusted user ID is required")
        self.storage_path = Path(storage_path)
        self.user_id = user_id
        self.recent_limit = recent_limit
        self.trend_settings = TrendSettings.model_validate(trend_settings or {})
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("Unsupported psychological database version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS states (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, history_scope TEXT NOT NULL,
                    timestamp REAL NOT NULL, payload TEXT NOT NULL,
                    import_key TEXT, UNIQUE(user_id, import_key)
                );
                CREATE INDEX IF NOT EXISTS state_user_time ON states(user_id, timestamp);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.storage_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _timestamp(state):
        return state.timestamp.replace(
            tzinfo=state.timestamp.tzinfo or timezone.utc
        ).timestamp()

    async def append(self, scope: str, state: PsychologicalState) -> str:
        return await to_thread(self._append, scope, state)

    def _append(self, scope, state):
        record_id = uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO states VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    record_id,
                    self.user_id,
                    scope,
                    self._timestamp(state),
                    state.model_dump_json(),
                ),
            )
        return record_id

    async def retrieve_recent(
        self, scope: str, limit: int | None = None
    ) -> list[PsychologicalState]:
        # scope is retained as provenance on write. Reads span this trusted user only.
        rows = await to_thread(
            self.list_records, limit=self.recent_limit if limit is None else limit
        )
        return [
            PsychologicalState.model_validate(row["state"]) for row in reversed(rows)
        ]

    def list_records(self, *, limit: int = 100, history_scope: str | None = None):
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        query = "SELECT * FROM states WHERE user_id=?"
        args = [self.user_id]
        if history_scope is not None:
            query += " AND history_scope=?"
            args.append(history_scope)
        query += " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
        args.append(limit)
        with self._connect() as db:
            rows = db.execute(query, args).fetchall()
        return [
            {
                "id": r["id"],
                "history_scope": r["history_scope"],
                "state": json.loads(r["payload"]),
            }
            for r in rows
        ]

    async def retrieve_trend(
        self, now: datetime | None = None
    ) -> StateTrend | DailyStateTrend:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Reference time requires a timezone")

        def read():
            with self._connect() as db:
                if self.trend_settings.version == "daily_v2":
                    # Stream one user's history to preserve last-observed evidence
                    # older than both windows. No persistent aggregate cache.
                    rows = db.execute(
                        "SELECT payload FROM states WHERE user_id=? AND timestamp<=? ORDER BY timestamp",
                        (self.user_id, now.timestamp()),
                    )

                    def states():
                        for row in rows:
                            payload = json.loads(row[0])
                            if "timestamp" not in payload:
                                payload["timestamp_known"] = False
                            yield PsychologicalState.model_validate(payload)

                    return summarize_daily_trend(states(), now, self.trend_settings)
                rows = db.execute(
                    "SELECT payload FROM states WHERE user_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                    (
                        self.user_id,
                        (now - timedelta(days=14)).timestamp(),
                        now.timestamp(),
                    ),
                ).fetchall()
            return summarize_trend(
                [PsychologicalState.model_validate_json(row[0]) for row in rows], now
            )

        return await to_thread(read)

    def correct(self, record_id: str, changes: dict) -> bool:
        allowed = {
            "emotion",
            "topics",
            "summary",
            "observed_dimensions",
            "interaction_feedback",
        }
        if not changes or not set(changes).issubset(allowed):
            raise ValueError(
                "Only emotion, topics, summary, observed_dimensions, interaction_feedback can be corrected"
            )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM states WHERE id=? AND user_id=?",
                (record_id, self.user_id),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row[0])
            changes = dict(changes)
            if "interaction_feedback" in changes:
                intent = (
                    payload.get("interaction_intent")
                    or InteractionIntent().model_dump()
                )
                intent.update(
                    feedback=changes.pop("interaction_feedback"),
                    feedback_source="user_correction",
                )
                payload["interaction_intent"] = InteractionIntent.model_validate(
                    intent
                ).model_dump()
            corrected_dimensions = list(changes.get("emotion", {}))
            if changes:
                original = PsychologicalState.model_validate(payload)
                origin = observation_source(original)
                provenance = {
                    dim: original.dimension_sources.get(dim, origin)
                    for dim in original.observed_dimensions
                }
                newly_observed = set(changes.get("observed_dimensions", [])) - set(
                    original.observed_dimensions
                )
                for dim in set(corrected_dimensions) | newly_observed:
                    provenance[dim] = "user_correction"
                payload["dimension_sources"] = provenance
                payload["topics_source"] = (
                    "user_correction"
                    if "topics" in changes
                    else original.topics_source or origin
                )
            if "emotion" in changes:
                changes = {
                    **changes,
                    "emotion": {**payload["emotion"], **changes["emotion"]},
                }
            if changes:
                payload.update(
                    changes,
                    schema_version=max(2, payload.get("schema_version", 1)),
                    estimator_source="user_correction",
                    confidence="user_reported",
                )
            if "emotion" in changes:
                payload["observed_dimensions"] = sorted(
                    set(payload.get("observed_dimensions", []))
                    | set(corrected_dimensions)
                )
            state = PsychologicalState.model_validate(payload)
            db.execute(
                "UPDATE states SET payload=? WHERE id=? AND user_id=?",
                (state.model_dump_json(), record_id, self.user_id),
            )
        return True

    def delete(
        self, *, record_id: str | None = None, history_scope: str | None = None
    ) -> int:
        query, args = "DELETE FROM states WHERE user_id=?", [self.user_id]
        if record_id is not None:
            query += " AND id=?"
            args.append(record_id)
        if history_scope is not None:
            query += " AND history_scope=?"
            args.append(history_scope)
        with self._connect() as db:
            db.execute("PRAGMA secure_delete=ON")
            count = db.execute(query, args).rowcount
        return count

    def import_jsonl(self, path: Path, scopes: set[str]) -> int:
        if not scopes:
            raise ValueError("Explicit legacy scope ownership mapping is required")
        # Validate before transaction; never partially import a malformed file.
        entries = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if "timestamp" not in payload.get("state", {}):
                payload["state"]["timestamp_known"] = False
            entry = PsychologicalMemoryEntry.model_validate(payload)
            if entry.scope in scopes:
                digest = hashlib.sha256(f"{number}:{line}".encode()).hexdigest()
                entries.append((entry, digest))
        imported = 0
        with self._connect() as db:
            for entry, digest in entries:
                imported += db.execute(
                    "INSERT OR IGNORE INTO states VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        uuid4().hex,
                        self.user_id,
                        entry.scope,
                        self._timestamp(entry.state),
                        entry.state.model_dump_json(),
                        digest,
                    ),
                ).rowcount
        return imported
