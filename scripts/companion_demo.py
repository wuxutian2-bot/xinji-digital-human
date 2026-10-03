"""Offline, explicitly synthetic companion demo. No model, ASR or speech claims."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402
from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent  # noqa: E402
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource  # noqa: E402
from open_llm_vtuber.config_manager.tts_preprocessor import TTSPreprocessorConfig  # noqa: E402
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.decision_client import RuleBasedDecisionClient  # noqa: E402
from open_llm_vtuber.mental_health.schemas import PsychologicalState  # noqa: E402
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService  # noqa: E402


class DemoDialogue:
    """Deterministic display text, NOT an inference from a trained model."""

    async def chat_completion(self, messages, system=None, tools=None):
        if "primary strategy: collaborative_problem_solving" in (system or ""):
            yield "【合成演示】可以先把明天的复习内容分成两项。你愿意的话，可以编辑成自己的一个小步骤。"
        elif "primary strategy: reflect_and_clarify" in (system or ""):
            yield "【合成演示】我们先梳理一下，最近最让你在意的是什么？"
        else:
            yield "【合成演示】我在听，你可以按自己的节奏说。"


class DemoAvatar:
    emo_map = {"neutral": 0, "sadness": 6, "joy": 3}

    def extract_emotion(self, text):
        return []


def make_agent(memory, avatar=None):
    return MentalHealthAgent(
        dialogue_client=DemoDialogue(),
        decision_client=RuleBasedDecisionClient(),
        safety_guard=ContextSafetyGuard(),
        state_estimator=ContextStateEstimator(),
        memory_service=memory,
        system="Offline synthetic interface demonstration.",
        live2d_model=avatar or DemoAvatar(),
        tts_preprocessor_config=TTSPreprocessorConfig(
            remove_special_char=True,
            translator_config={
                "translate_audio": False,
                "translate_provider": "deeplx",
            },
        ),
    )


async def seed(memory, value, days=3):
    now = datetime.now(timezone.utc)
    ids = []
    for offset in range(1, days + 1):
        ids.append(
            await memory.append(
                "synthetic:history",
                PsychologicalState(
                    timestamp=now - timedelta(days=offset),
                    estimator_source="context_v2",
                    observed_dimensions=["stress"],
                    emotion={"stress": value},
                ),
            )
        )
    return ids


async def say(agent, text):
    turn = uuid4().hex
    async for _ in agent.chat(
        BatchInput(
            texts=[TextData(source=TextSource.INPUT, content=text)],
            metadata={"companion_turn_id": turn, "synthetic_demo": True},
        )
    ):
        pass
    return agent.companion.get("turn", turn)


async def build_cases(output):
    output.mkdir(parents=True, exist_ok=False)

    def memory(name):
        return SqlitePsychologicalMemoryService(
            str(output / f"{name}.sqlite3"),
            name,
            trend_settings={"version": "daily_v2"},
        )

    result = {
        "synthetic": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dialogue": "fixed template; no model invocation",
        "audio": "not generated",
        "cases": [],
    }
    agent = make_agent(memory("preference"))
    before = await say(agent, "先别给建议，我只想说说")
    after = await say(agent, "现在可以给我建议了")
    assert before["final_strategy"] == "supportive_listening"
    assert after["final_strategy"] == "collaborative_problem_solving"
    result["cases"].append(
        {"name": "拒绝建议后转为求助", "before": before, "after": after}
    )
    mem = memory("correction")
    ids = await seed(mem, 0.8)
    agent = make_agent(mem)
    before = await say(agent, "今天聊一会儿")
    for record_id in ids:
        mem.correct(record_id, {"emotion": {"stress": 0.2}})
    agent.companion.invalidate_snapshots()
    after = await say(agent, "今天聊一会儿")
    assert before["final_strategy"] == "reflect_and_clarify"
    assert after["final_strategy"] == "supportive_listening"
    result["cases"].append(
        {"name": "纠正历史状态后下一轮重新读取", "before": before, "after": after}
    )
    pair = []
    for name, score in (("high_history", 0.8), ("low_history", 0.2)):
        mem = memory(name)
        await seed(mem, score)
        pair.append(await say(make_agent(mem), "今天聊一会儿"))
    assert pair[0]["final_strategy"] != pair[1]["final_strategy"]
    result["cases"].append(
        {
            "name": "相同输入不同历史",
            "input": "今天聊一会儿",
            "high": pair[0],
            "low": pair[1],
        }
    )
    (output / "cases.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def serve(output, port):
    """Use real product routes, WebSocket handler and conversation pipeline; stub only engines."""
    from fastapi import FastAPI, WebSocket
    from starlette.staticfiles import StaticFiles
    from starlette.websockets import WebSocketDisconnect
    import uvicorn
    from open_llm_vtuber.config_manager import read_yaml, validate_config
    from open_llm_vtuber.live2d_model import Live2dModel
    from open_llm_vtuber.local_profile_boundary import LocalProfileBoundaryMiddleware
    from open_llm_vtuber.mental_health.product_routes import init_product_routes
    from open_llm_vtuber.routes import init_webtool_routes
    from open_llm_vtuber.service_context import ServiceContext
    from open_llm_vtuber.websocket_handler import WebSocketHandler

    config = validate_config(
        read_yaml(str(ROOT / "config_templates/conf.ZH.default.yaml"))
    )
    config.system_config.trial_mode = True
    config.system_config.synthetic_demo = True
    config.system_config.trial_label = "离线合成演示 · 无模型/语音调用"
    config.system_config.port = port
    config.character_config.conf_uid = "synthetic_" + output.name
    config.character_config.conf_name = "心迹 · 合成演示"
    memory = SqlitePsychologicalMemoryService(
        str(output / "browser.sqlite3"),
        "synthetic-browser",
        trend_settings={"version": "daily_v2"},
    )
    if not memory.list_records():
        asyncio.run(seed(memory, 0.8, 10))
    avatar = Live2dModel(config.character_config.live2d_model_name)

    class TextOnlyTTS:
        supported_controls = frozenset()
        text_only = True

        async def async_generate_audio_with_options(self, **kwargs):
            return None

    def context():
        ctx = ServiceContext()
        ctx.config = config
        ctx.system_config = config.system_config
        ctx.character_config = config.character_config
        ctx.live2d_model = avatar
        ctx.agent_engine = make_agent(memory, avatar)
        ctx.tts_engine = TextOnlyTTS()
        return ctx

    class DemoHandler(WebSocketHandler):
        async def _init_service_context(self, send_text, client_uid):
            ctx = context()
            ctx.send_text, ctx.client_uid = send_text, client_uid
            return ctx

    ctx = context()
    handler = DemoHandler(ctx)
    app = FastAPI(title="心迹 · 合成演示（固定文字回复，无语音）")
    app.add_middleware(LocalProfileBoundaryMiddleware, port=port)
    app.include_router(init_product_routes(ctx))
    app.include_router(init_webtool_routes(ctx))

    @app.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        uid = uuid4().hex
        try:
            await handler.handle_new_connection(websocket, uid)
            await handler.handle_websocket_communication(websocket, uid)
        except WebSocketDisconnect:
            pass
        finally:
            await handler.handle_disconnect(uid)

    for prefix, directory in (
        ("live2d-models", "live2d-models"),
        ("avatars", "avatars"),
        ("bg", "backgrounds"),
    ):
        app.mount("/" + prefix, StaticFiles(directory=ROOT / directory))
    app.mount("/", StaticFiles(directory=ROOT / "frontend-src/dist/web", html=True))
    print(
        f"Synthetic UI: http://localhost:{port} (no real participant data)", flush=True
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory under private/demos"
    )
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reopen an existing synthetic UI profile; do not generate cases again",
    )
    parser.add_argument("--port", type=int, default=12401)
    args = parser.parse_args()
    output = args.output.resolve()
    if (ROOT / "private" / "demos").resolve() not in output.parents:
        parser.error("Use a new directory under private/demos")
    logger.remove()
    if args.resume:
        if not args.serve or not (output / "cases.json").is_file():
            parser.error(
                "--resume requires --serve and an existing synthetic cases.json"
            )
        if (
            json.loads((output / "cases.json").read_text(encoding="utf-8")).get(
                "synthetic"
            )
            is not True
        ):
            parser.error("Cannot reopen a non-synthetic profile")
    else:
        asyncio.run(build_cases(output))
        print(f"3 synthetic cases verified: {output / 'cases.json'}", flush=True)
    if args.serve:
        serve(output, args.port)


if __name__ == "__main__":
    main()
