"""Measure ten synthetic turns through MentalHealthAgent.chat with a local ORPO API."""

import argparse
import asyncio
from contextlib import aclosing
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from loguru import logger  # noqa: E402
from open_llm_vtuber.agent.agent_factory import AgentFactory  # noqa: E402
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource  # noqa: E402
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402

PROMPTS = (
    "今天要准备课堂展示，有点紧张，想聊一会儿。",
    "我已经写好了提纲，可是站上台还是会忘词。",
    "我现在想先说说这种感觉。",
    "其实昨天排练的时候，有一段讲得挺顺。",
    "能不能陪我梳理一下我最在意的事情？",
    "我最在意的是同学能听懂我的意思。",
    "我想试一个小步骤，你有什么建议？",
    "我决定今晚先向室友讲一遍开场。",
    "想到有个人愿意听，心里轻松了一点。",
    "今天先聊到这里，谢谢你。",
)


async def measure(config_path, mode, base_url=None):
    logger.remove()
    config = Config.model_validate(read_yaml(str(config_path)))
    character = config.character_config
    settings = character.agent_config.agent_settings.mental_health_agent.model_dump()
    dialogue = settings["dialogue"]
    if base_url:
        dialogue["base_url"] = base_url
        dialogue["llm_api_key"] = "local-benchmark"
    if urlsplit(dialogue["base_url"]).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The benchmark expects a local ORPO endpoint")
    if "orpo" not in dialogue["model"].lower():
        raise ValueError("Expected an ORPO serving model")
    settings["streaming_output"] = mode == "streaming"
    with TemporaryDirectory() as directory:
        settings["memory"].update(
            sqlite_path=str(Path(directory) / "state.db"),
            storage_path=str(Path(directory) / "state.jsonl"),
            user_id="latency-synthetic",
        )
        agent = AgentFactory.create_agent(
            "mental_health_agent",
            {"mental_health_agent": settings},
            {},
            character.persona_prompt,
            live2d_model=SimpleNamespace(
                emo_map={"neutral": 0, "sadness": 1, "joy": 3}
            ),
            tts_preprocessor_config=character.tts_preprocessor_config,
            system_config=config.system_config.model_dump(),
        )
        client = agent._llm._client.client
        generate = agent._llm.chat_completion
        first_delta = None
        start = 0.0

        async def timed_completion(*args, **kwargs):
            nonlocal first_delta
            async with aclosing(generate(*args, **kwargs)) as upstream:
                async for delta in upstream:
                    if first_delta is None and isinstance(delta, str) and delta.strip():
                        first_delta = perf_counter() - start
                    yield delta

        agent._llm.chat_completion = timed_completion
        first_sentences = []
        try:
            models = await asyncio.wait_for(client.models.list(), 10)
            if not any(
                item.id in {dialogue["model"], dialogue["model"] + ":latest"}
                for item in models.data
            ):
                raise RuntimeError("Configured ORPO model is unavailable")
            print(
                f"mode={mode} model={dialogue['model']} segment_method={settings['segment_method']}",
                flush=True,
            )
            print("turn first_delta_s first_yield_s completion_s", flush=True)
            for index, prompt in enumerate(PROMPTS, 1):
                batch = BatchInput(
                    texts=[TextData(source=TextSource.INPUT, content=prompt)],
                    metadata={
                        "synthetic_demo": True,
                        "companion_turn_id": f"latency-{index}",
                    },
                )
                first = None
                first_delta = None
                parts = []
                start = perf_counter()

                async def consume():
                    nonlocal first
                    async with aclosing(agent.chat(batch)) as stream:
                        async for item in stream:
                            if first is None and item.tts_text.strip():
                                first = perf_counter() - start
                            parts.append(item.display_text.text)

                await asyncio.wait_for(consume(), 180)
                duration = perf_counter() - start
                if (
                    first is None
                    or first_delta is None
                    or "Error calling the chat endpoint" in "".join(parts)
                ):
                    raise RuntimeError(f"Round {index} has no valid model response")
                first_sentences.append(first)
                print(
                    f"{index} {first_delta:.3f} {first:.3f} {duration:.3f}", flush=True
                )
        finally:
            await client.close()
    print(f"first_yield_p50_s={median(first_sentences):.3f}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument("--base-url", help="Override the local ORPO endpoint")
    parser.add_argument(
        "--mode", choices=["streaming", "buffered"], default="streaming"
    )
    args = parser.parse_args()
    asyncio.run(measure(args.config, args.mode, args.base_url))
