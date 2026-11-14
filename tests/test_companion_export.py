from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from open_llm_vtuber.local_profile_boundary import LocalProfileBoundaryMiddleware
from open_llm_vtuber.mental_health.companion_store import CompanionStore, companion_for
from open_llm_vtuber.mental_health.product_routes import init_product_routes
from open_llm_vtuber.mental_health.schemas import PsychologicalState
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService


class CompanionExportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.memory = SqlitePsychologicalMemoryService(
            str(Path(self.folder.name) / "states.db"), "owner"
        )
        self.agent = SimpleNamespace(_psychological_memory=self.memory)
        self.context = SimpleNamespace(
            agent_engine=self.agent,
            system_config=SimpleNamespace(
                trial_mode=True, synthetic_demo=True, trial_label="Synthetic"
            ),
        )
        app = FastAPI()
        app.add_middleware(LocalProfileBoundaryMiddleware, port=12407)
        app.include_router(init_product_routes(self.context))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://127.0.0.1:12407/api/companion",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_repeated_routes_reuse_the_agent_store_without_recreating_tables(
        self,
    ):
        original = CompanionStore.__init__
        calls = []

        def track(store, memory):
            calls.append(memory)
            original(store, memory)

        with patch.object(CompanionStore, "__init__", track):
            for route in ("/profile", "/actions", "/turns", "/export", "/profile"):
                self.assertEqual((await self.client.get(route)).status_code, 200)
        self.assertEqual(calls, [self.memory])
        self.assertIs(companion_for(self.agent), self.agent.companion)

    def test_cache_rebinds_on_database_user_or_memory_mode_change(self):
        first = companion_for(self.agent)
        replacement = SqlitePsychologicalMemoryService(
            str(Path(self.folder.name) / "other.db"), "owner"
        )
        self.agent._psychological_memory = replacement
        second = companion_for(self.agent)
        self.assertIsNot(first, second)
        replacement.user_id = "other-user"
        third = companion_for(self.agent)
        self.assertIsNot(second, third)
        self.assertEqual(third.user_id, "other-user")
        self.agent._psychological_memory = None
        self.assertIsNone(companion_for(self.agent))
        self.assertIsNone(self.agent.companion)

    def test_many_receipts_use_two_selects_and_remain_user_bound(self):
        store = companion_for(self.agent)
        rows = []
        for turn_id in ("one", "two", "three"):
            segments = [dict(id=i, has_audio=True, sent=True) for i in range(400)]
            rows.append(
                (
                    "owner",
                    "turn",
                    turn_id,
                    json.dumps(dict(id=turn_id, sent_segments=segments)),
                )
            )
            rows += [
                (
                    "owner",
                    "playback",
                    f"{turn_id}:{i}",
                    json.dumps({"status": "completed"}),
                )
                for i in range(400)
            ]
            rows.append(
                ("other", "playback", f"{turn_id}:0", json.dumps({"status": "failed"}))
            )
        with self.memory._connect() as db:
            db.executemany("INSERT INTO companion_items VALUES (?,?,?,?)", rows)
        original = self.memory._connect
        statements = []

        @contextmanager
        def tracked():
            with original() as db:
                db.set_trace_callback(statements.append)
                yield db

        with patch.object(self.memory, "_connect", tracked):
            turns = store.turns()
        self.assertEqual(
            len([s for s in statements if s.lstrip().upper().startswith("SELECT")]), 2
        )
        self.assertEqual(len(turns), 3)
        self.assertTrue(all(t["playback"] == "completed" for t in turns))
        self.assertTrue(
            all(s["playback"] == "completed" for t in turns for s in t["sent_segments"])
        )

    def test_batch_receipts_preserve_interruption_failure_silent_and_missing_semantics(
        self,
    ):
        store = companion_for(self.agent)
        for turn_id, extra, segments in (
            (
                "done",
                {},
                [dict(id=0, has_audio=True, sent=True), dict(id=1, has_audio=False)],
            ),
            (
                "interrupted",
                {"playback": "interrupted"},
                [dict(id=0, has_audio=True, sent=True)],
            ),
            ("failed", {}, [dict(id=0, has_audio=False, tts_error=True)]),
            ("missing", {}, [dict(id=0, has_audio=True, sent=True)]),
        ):
            store.put(
                "turn", turn_id, dict(id=turn_id, sent_segments=segments, **extra)
            )
        store.put("playback", "done:0", {"status": "completed"})
        store.put("playback", "interrupted:0", {"status": "failed"})
        result = {t["id"]: t for t in store.turns()}
        self.assertEqual(
            {key: t["playback"] for key, t in result.items()},
            {
                "done": "completed",
                "interrupted": "interrupted",
                "failed": "failed",
                "missing": "unconfirmed",
            },
        )
        self.assertEqual(result["done"]["sent_segments"][1]["playback"], "unconfirmed")
        self.assertEqual(store.export()["turns"], store.turns())

    async def test_export_is_complete_beyond_list_limits_and_excludes_other_user(self):
        store = companion_for(self.agent)
        payload = PsychologicalState(
            observed_dimensions=["stress"], emotion={"stress": 0, "anxiety": None}
        ).model_dump_json()
        with self.memory._connect() as db:
            db.executemany(
                "INSERT INTO states VALUES (?,?,?,?,?,NULL)",
                [(f"s{i}", "owner", "history", i, payload) for i in range(10005)],
            )
            db.execute(
                "INSERT INTO states VALUES (?,?,?,?,?,NULL)",
                ("foreign-state", "other", "foreign", 0, payload),
            )
            db.executemany(
                "INSERT INTO companion_items VALUES (?,?,?,?)",
                [
                    (
                        "owner",
                        kind,
                        f"{kind}{i}",
                        json.dumps({"id": f"{kind}{i}", "status": "completed"}),
                    )
                    for kind in ("turn", "action")
                    for i in range(1005)
                ],
            )
            db.execute(
                "INSERT INTO companion_items VALUES (?,?,?,?)",
                (
                    "other",
                    "turn",
                    "turn0",
                    json.dumps({"id": "turn0", "secret": "foreign-marker"}),
                ),
            )
            db.execute(
                "INSERT INTO companion_items VALUES (?,?,?,?)",
                (
                    "other",
                    "action",
                    "action0",
                    json.dumps({"id": "action0", "secret": "foreign-marker"}),
                ),
            )
        response = await self.client.get("/export?user_id=other")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user_id"], "owner")
        self.assertTrue(data["synthetic_demo"])
        self.assertEqual(
            (len(data["states"]), len(data["turns"]), len(data["actions"])),
            (10005, 1005, 1005),
        )
        self.assertEqual(data["states"][0]["state"]["emotion"]["stress"], 0)
        self.assertIsNone(data["states"][0]["state"]["emotion"]["anxiety"])
        self.assertNotIn("foreign-marker", response.text)
        self.assertNotIn("foreign-state", response.text)
        self.assertEqual(len(store.list("action")), 100)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertRegex(
            response.headers["content-disposition"],
            r'^attachment; filename="xinji-data-\d{8}T\d{6}Z\.json"$',
        )
        self.assertTrue(response.headers["content-type"].startswith("application/json"))

    async def test_export_uses_the_new_server_profile_and_not_the_old_cache(self):
        first = companion_for(self.agent)
        first.put("action", "same", {"id": "same", "text": "old-owner"})
        new_memory = SqlitePsychologicalMemoryService(
            str(self.memory.storage_path), "other"
        )
        new_store = CompanionStore(new_memory)
        new_store.put("action", "same", {"id": "same", "text": "new-owner"})
        self.agent._psychological_memory = new_memory
        data = (await self.client.get("/export")).json()
        self.assertEqual(data["user_id"], "other")
        self.assertEqual(data["actions"], [{"id": "same", "text": "new-owner"}])
        self.assertIs(self.agent.companion.memory, new_memory)
        self.agent._psychological_memory = None
        self.assertEqual((await self.client.get("/export")).status_code, 503)
        self.assertIsNone(self.agent.companion)

    async def test_export_empty_profile_and_existing_local_origin_boundary(self):
        response = await self.client.get("/export")
        data = response.json()
        self.assertEqual((data["states"], data["turns"], data["actions"]), ([], [], []))
        for headers in (
            {"Origin": "https://foreign.invalid"},
            {"Host": "foreign.invalid:12407"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(
                (await self.client.get("/export", headers=headers)).status_code, 403
            )

    def test_export_reads_all_collections_from_one_snapshot(self):
        store = companion_for(self.agent)
        store.put("action", "a", {"id": "a", "text": "before"})
        original = self.memory._connect
        changed = False

        @contextmanager
        def observed():
            with original() as db:

                def trace(statement):
                    nonlocal changed
                    if statement.startswith("SELECT kind,id,payload") and not changed:
                        changed = True
                        with original() as writer:
                            writer.execute(
                                "UPDATE companion_items SET payload=? WHERE user_id=? AND kind='action' AND id='a'",
                                (json.dumps({"id": "a", "text": "after"}), "owner"),
                            )

                db.set_trace_callback(trace)
                yield db

        with patch.object(self.memory, "_connect", observed):
            exported = store.export()
        self.assertTrue(changed)
        self.assertEqual(exported["actions"][0]["text"], "before")
        self.assertEqual(store.get("action", "a")["text"], "after")
