"""Synthetic real-SDK concurrent requests, cancellation and recovery check."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import httpx
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402
from open_llm_vtuber.mental_health.decision_client import (  # noqa: E402
    FallbackDecisionClient,
    OpenAICompatibleDecisionClient,
)
from open_llm_vtuber.mental_health.schemas import (  # noqa: E402
    DecisionContext,
    PsychologicalState,
    SafetyCheckResult,
)


async def evaluate(settings):
    requests = []

    async def on_request(request):
        # Count SDK transport attempts without storing prompts or authorization.
        requests.append({"method": request.method, "path": request.url.path})

    async with httpx.AsyncClient(
        event_hooks={"request": [on_request]}, trust_env=False
    ) as http:
        async with AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.base_url,
            max_retries=0,
            http_client=http,
        ) as sdk:
            primary = OpenAICompatibleDecisionClient(
                **settings.model_dump(exclude={"enabled"}), client=sdk
            )
            client = FallbackDecisionClient(primary)

            def context(text):
                return DecisionContext(
                    user_text=text,
                    current_state=PsychologicalState(),
                    safety=SafetyCheckResult(action="allow"),
                )

            started = perf_counter()
            pair = await asyncio.gather(
                client.decide(context("你好，今天想找人聊聊。")),
                client.decide(context("我想理清这件事。")),
            )
            pair_seconds = perf_counter() - started
            before = len(requests)
            task = asyncio.create_task(
                client.decide(context("这是一次虚构的取消测试。"))
            )
            await asyncio.sleep(0.2)
            task.cancel()
            cancelled = False
            try:
                await task
            except asyncio.CancelledError:
                cancelled = True
            cancel_requests = len(requests) - before
            recovered = await client.decide(context("取消后继续：你好。"))
            return {
                "synthetic_only": True,
                "model": settings.model,
                "timeout_seconds": settings.timeout_seconds,
                "request_count": len(requests),
                "transport_attempts": requests,
                "concurrent_sources": [result.trace.source for result in pair],
                "concurrent_total_seconds": pair_seconds,
                "distinct_result_and_trace_objects": pair[0] is not pair[1]
                and pair[0].trace is not pair[1].trace,
                "cancelled": cancelled,
                "cancel_transport_attempts": cancel_requests,
                "recovery_source": recovered.trace.source,
                "recovery_latency_ms": recovered.trace.latency_ms,
                "passed": all(result.trace.source == "model" for result in pair)
                and cancelled
                and cancel_requests == 1
                and recovered.trace.source == "model"
                and len(requests) == 4,
                "limitations": [
                    "Client cancellation plus recovery observed; server memory release not inferred",
                    "Two concurrent synthetic requests are not a multi-user capacity benchmark",
                ],
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output path")
    try:
        settings = Config.model_validate(
            read_yaml(str(args.config))
        ).character_config.agent_config.agent_settings.mental_health_agent.decision
        if not settings.enabled:
            raise ValueError("Decision is disabled")
        report = asyncio.run(evaluate(settings))
        report["source_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
        print(
            f"Lifecycle passed={report['passed']}; HTTP attempts={report['request_count']}"
        )
        return 0 if report["passed"] else 1
    except Exception as error:
        print(f"Lifecycle check failed ({type(error).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
