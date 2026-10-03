"""Product API for the active server-side local profile."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .companion_store import companion_for, utc_now
from .long_term import DIMENSIONS, SOURCES
from .schemas import UserStateReport


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Correction(StrictBody):
    emotion: dict[Literal["stress", "anxiety", "low_mood"], float] = Field(min_length=1)


class Feedback(StrictBody):
    value: Literal["helpful", "unhelpful", "unspecified"]


class ActionCreate(StrictBody):
    text: str = Field(min_length=1, max_length=300)
    turn_id: str = Field(min_length=1, max_length=64)


class ActionUpdate(StrictBody):
    status: Literal["pending", "completed", "skipped"]
    feedback: Literal["helpful", "unhelpful", "unspecified"] = "unspecified"


class Consent(StrictBody):
    accepted: bool
    retain_conversation: bool = False


class ExperienceEvent(StrictBody):
    name: Literal[
        "visit", "task_complete", "task_failed", "return_visit", "interview_complete"
    ]
    duration_ms: float | None = Field(None, ge=0, le=86400000, allow_inf_nan=False)
    outcome: Literal["independent", "assisted", "abandoned"] | None = None


def weekly_review(trend):
    labels = {"stress": "压力", "anxiety": "焦虑感", "low_mood": "低落感"}
    origins = {
        "system_estimate": "系统估计",
        "user_report": "你的自报",
        "user_correction": "你的纠正",
    }
    lines = []
    for source in SOURCES:
        for dim in DIMENSIONS:
            m = trend["sources"][source]["dimensions"][dim]
            days = m["observed_days"]
            if not days:
                continue
            line = f"{origins[source]}·{labels[dim]}：本周有 {days}/7 天记录"
            if m["eligible_for_decision"] and m["mean"] is not None:
                line += f"，日均值的均值为 {m['mean'] * 10:.1f}/10"
            else:
                line += "，记录不足或已过期，暂不据此推断变化"
            if m["change"] is not None:
                line += f"，较前一周变化 {(m['change'] * 10 or 0):+.1f}"
            lines.append(line + "。")
    return lines or [
        "还没有足够的记录。可以从今天的一次自报开始，未填写的维度会保持未知。"
    ]


def init_product_routes(context):
    def no_cache(response: Response):
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(
        prefix="/api/companion", tags=["心迹"], dependencies=[Depends(no_cache)]
    )

    def store():
        result = companion_for(getattr(context, "agent_engine", None))
        if result is None:
            raise HTTPException(503, "我的心迹需要本机 SQLite 档案模式。")
        return result

    def item(kind, item_id):
        value = store().get(kind, item_id)
        if value is None:
            raise HTTPException(404, "当前档案中没有这条记录。")
        return value

    def writable_store():
        s = store()
        if context.system_config.trial_mode and not (
            s.get("consent", "current") or {}
        ).get("accepted"):
            raise HTTPException(403, "请先阅读体验说明并选择是否参加。")
        return s

    @router.get("/profile")
    def profile(response: Response):
        response.headers["Cache-Control"] = "no-store"
        s = store()
        system = context.system_config
        return {
            "label": system.trial_label,
            "trial_mode": system.trial_mode,
            "synthetic_demo": system.synthetic_demo,
            "consent": s.get("consent", "current"),
        }

    @router.put("/consent")
    def consent(body: Consent):
        s = store()
        body.retain_conversation = body.accepted and body.retain_conversation
        result = s.put(
            "consent", "current", {**body.model_dump(), "timestamp": utc_now()}
        )
        s.event("consent_updated")
        return result

    @router.get("/states")
    def records(limit: int = Query(100, ge=1, le=1000)):
        return store().memory.list_records(limit=limit)

    @router.post("/states", status_code=201)
    async def self_report(body: UserStateReport):
        if body.timestamp > datetime.now(timezone.utc):
            raise HTTPException(422, "记录时间不能晚于现在。")
        s = writable_store()
        record_id = await s.memory.append("manual:self-report", body.to_state())
        s.event("self_report_created")
        return {"id": record_id}

    @router.patch("/states/{record_id}")
    def correct(record_id: str, body: Correction):
        s = writable_store()
        try:
            found = s.memory.correct(record_id, body.model_dump())
        except ValueError:
            raise HTTPException(422, "分数必须在 0～1 之间。") from None
        if not found:
            raise HTTPException(404, "记录不存在。")
        s.invalidate_snapshots()
        s.event("state_corrected")
        return {"ok": True}

    @router.delete("/states/{record_id}")
    def delete(record_id: str):
        s = store()
        if not s.memory.delete(record_id=record_id):
            raise HTTPException(404, "记录不存在。")
        s.invalidate_snapshots(deleted_record_id=record_id)
        s.event("state_deleted")
        return {"ok": True}

    @router.get("/trend")
    async def trend():
        result = await store().memory.retrieve_trend()
        if result.version != "daily_v2":
            raise HTTPException(409, "请为当前档案配置 daily_v2 趋势。")
        data = result.model_dump(mode="json")
        return {"trend": data, "review": weekly_review(data)}

    @router.get("/turns")
    def turns(limit: int = Query(100, ge=1, le=1000)):
        return store().turns(limit)

    @router.put("/turns/{turn_id}/feedback")
    def feedback(turn_id: str, body: Feedback):
        s = writable_store()
        turn = item("turn", turn_id)
        if turn.get("record_id"):
            s.memory.correct(turn["record_id"], {"interaction_feedback": body.value})
        result = s.update_turn(
            turn_id, feedback=body.value, feedback_updated_at=utc_now()
        )
        s.event("response_feedback", outcome=body.value)
        return result

    @router.get("/actions")
    def actions():
        return store().list("action")

    @router.post("/actions", status_code=201)
    def create_action(body: ActionCreate):
        writable_store()
        turn = item("turn", body.turn_id)
        if turn.get("final_strategy") != "collaborative_problem_solving":
            raise HTTPException(409, "请先明确选择一起想办法，再保存你确认的小步骤。")
        try:
            return store().create_action(body.text, body.turn_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @router.patch("/actions/{action_id}")
    def update_action(action_id: str, body: ActionUpdate):
        s = writable_store()
        action = item("action", action_id)
        if body.status == "pending" and action["status"] != "pending":
            raise HTTPException(409, "已结束的小步骤不能重新打开，请新建。")
        if body.status != "completed" and body.feedback != "unspecified":
            raise HTTPException(422, "请完成小步骤后再评价帮助程度。")
        result = s.put(
            "action",
            action_id,
            {**action, **body.model_dump(), "updated_at": utc_now()},
        )
        s.event("action_updated", outcome=body.status)
        return result

    @router.post("/events", status_code=201)
    def event(body: ExperienceEvent):
        return writable_store().event(**body.model_dump())

    return router
