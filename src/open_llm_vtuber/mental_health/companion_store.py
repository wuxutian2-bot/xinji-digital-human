"""Local, user-bound product records. Never a public authentication boundary."""

from datetime import datetime, timezone
import json
from uuid import uuid4

from .sqlite_memory import SqlitePsychologicalMemoryService


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class CompanionStore:
    def __init__(self, memory: SqlitePsychologicalMemoryService):
        self.memory = memory
        self.user_id = memory.user_id
        with memory._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS companion_items (
                    user_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(user_id, kind, id)
                );
            """)

    def get(self, kind, item_id):
        with self.memory._connect() as db:
            row = db.execute(
                "SELECT payload FROM companion_items WHERE user_id=? AND kind=? AND id=?",
                (self.user_id, kind, item_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, item_id, payload):
        with self.memory._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO companion_items VALUES (?,?,?,?)",
                (self.user_id, kind, item_id, json.dumps(payload, ensure_ascii=False)),
            )
        return payload

    def list(self, kind, limit=100):
        with self.memory._connect() as db:
            rows = db.execute(
                "SELECT payload FROM companion_items WHERE user_id=? AND kind=? ORDER BY rowid DESC LIMIT ?",
                (self.user_id, kind, limit),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def update_turn(self, turn_id, **changes):
        # Transactions prevent playback/feedback from overwriting each other.
        with self.memory._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM companion_items WHERE user_id=? AND kind='turn' AND id=?",
                (self.user_id, turn_id),
            ).fetchone()
            if not row:
                return None
            payload = {**json.loads(row[0]), **changes}
            db.execute(
                "UPDATE companion_items SET payload=? WHERE user_id=? AND kind='turn' AND id=?",
                (json.dumps(payload, ensure_ascii=False), self.user_id, turn_id),
            )
        return payload

    def invalidate_snapshots(self, deleted_record_id=None):
        with self.memory._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id,payload FROM companion_items WHERE user_id=? AND kind='turn'",
                (self.user_id,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row[1])
                if deleted_record_id and payload.get("record_id") == deleted_record_id:
                    for segment in payload.get("sent_segments", []):
                        db.execute(
                            "DELETE FROM companion_items WHERE user_id=? AND kind='playback' AND id=?",
                            (self.user_id, f"{row[0]}:{segment['id']}"),
                        )
                    db.execute(
                        "DELETE FROM companion_items WHERE user_id=? AND kind='turn' AND id=?",
                        (self.user_id, row[0]),
                    )
                else:
                    payload["history_context"] = None
                    payload["history_invalidated"] = True
                    db.execute(
                        "UPDATE companion_items SET payload=? WHERE user_id=? AND kind='turn' AND id=?",
                        (json.dumps(payload, ensure_ascii=False), self.user_id, row[0]),
                    )

    def event(self, name, *, duration_ms=None, outcome=None):
        # No arbitrary text or caller-supplied attributes accepted.
        event_id = uuid4().hex
        return self.put(
            "event",
            event_id,
            {
                "id": event_id,
                "timestamp": utc_now(),
                "name": name,
                "duration_ms": duration_ms,
                "outcome": outcome,
            },
        )

    def create_action(self, text, turn_id):
        with self.memory._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT payload FROM companion_items WHERE user_id=? AND kind='action'",
                (self.user_id,),
            ).fetchall()
            if any(json.loads(r[0])["status"] == "pending" for r in rows):
                raise ValueError("请先完成或跳过当前的小步骤。")
            action = {
                "id": uuid4().hex,
                "text": text,
                "turn_id": turn_id,
                "created_at": utc_now(),
                "status": "pending",
                "feedback": "unspecified",
            }
            db.execute(
                "INSERT INTO companion_items VALUES (?,?,?,?)",
                (
                    self.user_id,
                    "action",
                    action["id"],
                    json.dumps(action, ensure_ascii=False),
                ),
            )
        self.event("action_created")
        return action

    def record_playback(self, turn_id, segment_id, status, scope):
        turn = self.get("turn", turn_id)
        if not turn or turn.get("scope") != scope:
            raise ValueError("Unknown conversation turn")
        segments = turn.get("sent_segments", [])
        if type(segment_id) is not int or not 0 <= segment_id < len(segments):
            raise ValueError("Unknown audio segment")
        if status not in {"completed", "failed", "silent"}:
            raise ValueError("Invalid playback status")
        if status == "completed" and not segments[segment_id]["has_audio"]:
            raise ValueError("Silent text is not completed audio")
        self.put(
            "playback",
            f"{turn_id}:{segment_id}",
            {"status": status, "timestamp": utc_now()},
        )

    def turns(self, limit=100):
        turns = self.list("turn", limit)
        for turn in turns:
            for segment in turn.get("sent_segments", []):
                receipt = self.get("playback", f"{turn['id']}:{segment['id']}")
                segment["playback"] = receipt["status"] if receipt else "unconfirmed"
            audio = [s for s in turn.get("sent_segments", []) if s["has_audio"]]
            if turn.get("playback") != "interrupted":
                turn["playback"] = (
                    "failed"
                    if any(
                        s.get("tts_error") or s["playback"] == "failed"
                        for s in turn.get("sent_segments", [])
                    )
                    else "completed"
                    if audio
                    and all(
                        s.get("sent") and s["playback"] == "completed" for s in audio
                    )
                    else "unconfirmed"
                )
        return turns


def companion_for(agent):
    memory = getattr(agent, "_psychological_memory", None)
    return (
        CompanionStore(memory)
        if isinstance(memory, SqlitePsychologicalMemoryService)
        else None
    )
