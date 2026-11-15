"""Profile-bound voice design previews, never arbitrary uploaded voice clones."""

import asyncio
from hashlib import sha256
import json
import re
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..tts.breeze_tts import PREVIEW_TEXT, TTSEngine
from .companion_store import utc_now


class VoiceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: str = Field(pattern=r"^(default|preset|custom)$")
    preset_id: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, min_length=1, max_length=200)
    seed: int = Field(42, ge=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def validate_choice(self):
        if self.mode == "preset" and (
            not self.preset_id or self.description is not None
        ):
            raise ValueError("Preset mode requires only preset_id")
        if self.mode == "custom" and (
            not self.description or self.preset_id is not None
        ):
            raise ValueError("Custom mode requires only description")
        if self.mode == "default" and (
            self.description is not None or self.preset_id is not None
        ):
            raise ValueError("Default mode has no custom voice fields")
        if self.description and re.search(
            r"模仿|克隆|复刻|仿照|真人|明星|名人|声优|[像用].{1,16}(?:本人|的声音|的嗓音|的声线)|"
            r"\b(?:imitate|impersonate|clone|celebrity|sound like|voice of)\b",
            self.description,
            re.I,
        ):
            raise ValueError("不支持模仿具体真人，请描述音高、语气和音色特征。")
        return self


class VoicePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    preset_id: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, min_length=1, max_length=200)
    seed: int = Field(42, ge=0, le=2147483647, strict=True)

    def selection(self):
        return VoiceSelection(
            mode="preset" if self.preset_id is not None else "custom",
            **self.model_dump(),
        )

    @model_validator(mode="after")
    def validate_choice(self):
        self.selection()
        return self


class VoicePreferences:
    """One service per product router. Draft audio is ephemeral, bounded and user-bound."""

    def __init__(self):
        self._drafts = {}
        self._locks = {}

    @staticmethod
    def key(store):
        # Include database identity: two independent profiles can share a user ID.
        return str(store.memory.storage_path.resolve()), store.user_id

    def lock(self, store):
        return self._locks.setdefault(self.key(store), asyncio.Lock())

    @staticmethod
    def engine(context):
        engine = getattr(context, "tts_engine", None)
        return engine if isinstance(engine, TTSEngine) else None

    @staticmethod
    def preset(engine, preset_id):
        preset = engine.presets.get(preset_id)
        if not preset:
            raise HTTPException(422, "请选择当前角色提供的音色预设。")
        return preset

    async def status(self, context, store):
        engine = self.engine(context)
        return {
            "available": bool(engine and await engine.available()),
            "preference": store.get("voice_preference", "current"),
            "presets": [
                {
                    "id": key,
                    "label": value["label"],
                    "description": value.get("description", ""),
                }
                for key, value in (engine.presets.items() if engine else [])
            ],
            "preview_attempts": self.attempts(store)["count"],
        }

    @staticmethod
    def attempts(store):
        state = store.get("voice_preview", "current") or {}
        if time.time() - state.get("started_at", 0) >= 1800:
            return {"count": 0, "started_at": time.time()}
        return state

    def prune(self):
        now = time.monotonic()
        self._drafts = {
            k: v for k, v in self._drafts.items() if now - v["created"] < 600
        }

    async def preview(self, context, store, choice):
        engine = self.engine(context)
        if not engine:
            raise HTTPException(503, "当前声音服务不支持试听。")
        async with self.lock(store):
            if choice.mode == "preset":
                preset = self.preset(engine, choice.preset_id)
                return await engine.synthesize_wav(
                    PREVIEW_TEXT, voice_id=preset["voice_id"]
                )
            state = self.attempts(store)
            if state["count"] >= 5:
                raise HTTPException(
                    429, "本次已生成 5 次，请先选择声音或使用默认声音，稍后再试。"
                )
            # Count attempts before GPU work, including failures and overlapping calls.
            state["count"] += 1
            store.put("voice_preview", "current", state)
            self.prune()
            self._drafts.pop(self.key(store), None)
            wav = await engine.synthesize_wav(
                PREVIEW_TEXT,
                voice_id="",
                instruction=choice.description,
                seed=choice.seed,
            )
            self._drafts[self.key(store)] = {
                "description": choice.description,
                "seed": choice.seed,
                "wav": wav,
                "created": time.monotonic(),
                "engine": engine,
            }
            return wav

    async def save(self, context, store, choice):
        async with self.lock(store):
            engine = self.engine(context)
            preference = {"mode": choice.mode, "timestamp": utc_now()}
            if choice.mode != "default" and not engine:
                raise HTTPException(503, "当前声音服务不可用，可以使用默认声音。")
            if choice.mode == "preset":
                preset = self.preset(engine, choice.preset_id)
                preference.update(
                    preset_id=choice.preset_id, voice_id=preset["voice_id"]
                )
            elif choice.mode == "custom":
                self.prune()
                draft = self._drafts.get(self.key(store))
                if (
                    not draft
                    or draft["engine"] is not engine
                    or any(
                        draft[field] != getattr(choice, field)
                        for field in ("description", "seed")
                    )
                ):
                    raise HTTPException(409, "请先为当前描述生成试听，再确认使用。")
                owner = sha256("\0".join(self.key(store)).encode()).hexdigest()[:16]
                name = f"user_{owner}_{uuid4().hex[:12]}"
                await engine.register_voice(name, draft["wav"])
                # Track every created custom voice so changing settings never
                # orphans a file that profile deletion must later remove.
                store.put(
                    "voice_owned", name, {"voice_id": name, "base_url": engine.base_url}
                )
                preference.update(
                    voice_id=name, description=choice.description, seed=choice.seed
                )
            store.put("voice_preference", "current", preference)
            store.put(
                "voice_preview", "current", {"count": 0, "started_at": time.time()}
            )
            store.event("voice_preference_updated")
            self._drafts.pop(self.key(store), None)
            return preference

    async def delete_profile(self, context, store):
        async with self.lock(store):
            engine = self.engine(context)
            with store.memory._connect() as db:
                names = db.execute(
                    "SELECT id,payload FROM companion_items WHERE user_id=? AND kind='voice_owned'",
                    (store.user_id,),
                ).fetchall()
            if names and (not engine or not engine.voices_dir):
                raise HTTPException(
                    503,
                    "请先恢复原 Breeze 服务并配置 voices_dir，以便完整删除自定义音色。",
                )
            if any(
                json.loads(row["payload"])["base_url"] != engine.base_url
                for row in names
            ):
                raise HTTPException(409, "请先恢复创建自定义音色时的 Breeze 服务。")
            for row in names:
                await engine.delete_voice(row["id"])
            with store.memory._connect() as db:
                db.execute("PRAGMA secure_delete=ON")
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM states WHERE user_id=?", (store.user_id,))
                db.execute(
                    "DELETE FROM companion_items WHERE user_id=?", (store.user_id,)
                )
            self._drafts.pop(self.key(store), None)
