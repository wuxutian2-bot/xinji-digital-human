"""Reproducible synthetic evaluation through MentalHealthAgent, with Safety always on."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent  # noqa: E402
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource  # noqa: E402
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402
from open_llm_vtuber.mental_health.decision_client import (  # noqa: E402
    FallbackDecisionClient,
    OpenAICompatibleDecisionClient,
    RuleBasedDecisionClient,
)  # noqa: E402
from open_llm_vtuber.mental_health.dialogue_client import DialogueClient  # noqa: E402
from open_llm_vtuber.mental_health.memory_service import (  # noqa: E402
    DisabledPsychologicalMemoryService,
)  # noqa: E402
from open_llm_vtuber.mental_health.safety_guard import RuleBasedSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.schemas import PsychologicalState, SafetyAction  # noqa: E402
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService  # noqa: E402
from open_llm_vtuber.mental_health.state_estimator import KeywordStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402


class BenchmarkDialogue:
    def __init__(self, client=None, model=None):
        self.client, self.model = client, model
        self.calls = 0
        self.raw = ""
        self.completions = []

    async def chat_completion(self, messages, system=None, tools=None):
        self.calls += 1
        if self.client is None:
            self.raw = "我听到了你的感受。你愿意再说说吗？"
        else:
            result = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}]
                    + DialogueClient._merge_adjacent_turns(messages),
                    stream=False,
                    temperature=0,
                    max_tokens=384,
                ),
                timeout=60,
            )
            self.raw = result.choices[0].message.content or ""
            self.completions.append(
                {
                    "finish_reason": result.choices[0].finish_reason,
                    "usage": result.usage.model_dump() if result.usage else None,
                    "response_model": result.model,
                }
            )
        yield self.raw


class UnavailableDecision:
    async def decide(self, context):
        raise ConnectionError("synthetic service failure")


class RecordingDecision:
    def __init__(self, client):
        self.client = client
        self.traces = []
        self.results = []
        self.states = []

    async def decide(self, context):
        result = await self.client.decide(context)
        self.traces.append(result.trace.model_dump())
        self.results.append(result.model_dump())
        self.states.append(context.current_state)
        return result


def provenance(fixtures: Path):
    paths = sorted((ROOT / "src/open_llm_vtuber/mental_health").glob("*.py"))
    paths += [
        ROOT / "src/open_llm_vtuber/agent/agents/mental_health_agent.py",
        Path(__file__),
    ]
    files = {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {
        "upstream_commit": commit,
        "source_sha256": files,
        "fixtures_sha256": hashlib.sha256(fixtures.read_bytes()).hexdigest(),
    }


async def evaluate(args):
    config = Config.model_validate(read_yaml(str(args.config)))
    settings = config.character_config.agent_config.agent_settings.mental_health_agent
    fixture = json.loads(args.fixtures.read_text(encoding="utf-8"))
    guard, estimator = (
        (ContextSafetyGuard(), ContextStateEstimator())
        if settings.context_version == 2
        else (RuleBasedSafetyGuard(), KeywordStateEstimator())
    )
    sdk = None
    remote_decision = None
    if args.dialogue == "model":
        sdk = AsyncOpenAI(
            base_url=settings.dialogue.base_url,
            api_key=settings.dialogue.llm_api_key,
            timeout=60,
            max_retries=0,
        )
    if args.decision == "model":
        if not settings.decision.enabled:
            raise ValueError(
                "Independent Decision API must be enabled for model evaluation"
            )
        remote_decision = OpenAICompatibleDecisionClient(
            **settings.decision.model_dump(exclude={"enabled"})
        )
    rows = []
    try:
        # Verify readiness before dispatching an entire fixture to offline services.
        for client, expected in (
            (sdk, args.model or settings.dialogue.model),
            (
                remote_decision._client if remote_decision else None,
                settings.decision.model,
            ),
        ):
            if client is not None:
                advertised = await asyncio.wait_for(client.models.list(), timeout=5)
                if expected not in {item.id for item in advertised.data}:
                    raise ValueError("Requested evaluation model is not advertised")
        for case in fixture["cases"]:
            pre = await guard.check_input(case["text"])
            state1 = await estimator.estimate(case["text"], pre)
            state2 = await estimator.estimate(case["text"], pre)
            with TemporaryDirectory() as temp:
                memory = (
                    SqlitePsychologicalMemoryService(
                        str(Path(temp) / "states.db"), "synthetic-user"
                    )
                    if args.memory
                    else DisabledPsychologicalMemoryService()
                )
                for historic in case.get("history", []):
                    await memory.append(
                        "previous-history",
                        PsychologicalState(
                            timestamp=datetime.now(timezone.utc)
                            - timedelta(days=historic["days_ago"]),
                            schema_version=2,
                            estimator_source="keyword_v1",
                            confidence="low",
                            emotion={"stress": historic.get("stress", 0)},
                            observed_dimensions=["stress"]
                            if "stress" in historic
                            else [],
                            topics=["work"] if "stress" in historic else [],
                        ),
                    )
                dialogue = BenchmarkDialogue(sdk, args.model or settings.dialogue.model)
                decision = (
                    FallbackDecisionClient(UnavailableDecision())
                    if case.get("decision_failure")
                    else FallbackDecisionClient(remote_decision)
                    if remote_decision
                    else RuleBasedDecisionClient()
                )
                decision = RecordingDecision(decision)
                agent = MentalHealthAgent(
                    dialogue_client=dialogue,
                    decision_client=decision,
                    safety_guard=guard,
                    state_estimator=estimator,
                    memory_service=memory,
                    system=config.character_config.persona_prompt,
                    live2d_model=SimpleNamespace(
                        emo_map={"neutral": 0, "sadness": 1, "fear": 1, "joy": 3}
                    ),
                    tts_preprocessor_config=config.character_config.tts_preprocessor_config,
                    faster_first_response=False,
                    segment_method="regex",
                    expression_enabled=args.expression,
                    decision_protocol_version=settings.decision.protocol_version,
                )
                started = perf_counter()
                responses, actions, error = [], [], None
                try:
                    for text in [case["text"], *case.get("followups", [])]:
                        outputs = [
                            item
                            async for item in agent.chat(
                                BatchInput(
                                    texts=[
                                        TextData(source=TextSource.INPUT, content=text)
                                    ]
                                )
                            )
                        ]
                        responses.append(
                            "".join(item.display_text.text for item in outputs)
                        )
                        actions.append(outputs[0].actions.to_dict() if outputs else {})
                except Exception as caught:
                    error = type(caught).__name__
                records = await memory.retrieve_recent("current")
                trace = (
                    records[-1].decision_trace.model_dump()
                    if records and records[-1].decision_trace
                    else None
                )
                final_strategies = [
                    state.interaction_strategy for state in decision.states
                ]
                if not final_strategies and pre.action == SafetyAction.ESCALATE:
                    if trace and trace["source"] == "safety_gate":
                        final_strategies = [records[-1].interaction_strategy]
                    elif actions and actions[0].get("strategy"):
                        final_strategies = [actions[0]["strategy"]["primary"]]
                expected = case.get("expected_strategies")
                row = {
                    "id": case["id"],
                    "category": case["category"],
                    "expected_escalation": case["expect_escalation"],
                    "actual_escalation": pre.action == SafetyAction.ESCALATE,
                    "risk": pre.risk_level.value,
                    "dialogue_calls": dialogue.calls,
                    "completions": dialogue.completions,
                    "state_repeat_consistent": state1.model_dump(exclude={"timestamp"})
                    == state2.model_dump(exclude={"timestamp"}),
                    "state": state1.model_dump(mode="json"),
                    "responses": responses,
                    "actions": actions,
                    "decision_trace": trace,
                    "seconds": round(perf_counter() - started, 3),
                    "error": error,
                    "decision_calls": len(decision.results),
                    "decisions": decision.results,
                    "decisions_stage": "proposed_before_local_coordination",
                    "final_strategies": final_strategies,
                    "expected_strategies": expected,
                    "strategy_expectations_met": final_strategies == expected
                    if expected and final_strategies
                    else None,
                    "interaction_intents": [
                        state.interaction_intent.model_dump()
                        for state in decision.states
                    ],
                    "coordination_traces": [
                        state.decision_trace.coordination.model_dump()
                        if state.decision_trace and state.decision_trace.coordination
                        else None
                        for state in decision.states
                    ],
                    "decision_traces": decision.traces,
                    "raw_output_safety_action": (
                        await guard.check_output(dialogue.raw)
                    ).action.value
                    if dialogue.calls
                    else None,
                    "human_ratings": {
                        "supportiveness": None,
                        "coherence": None,
                        "unsupported_diagnosis": None,
                    },
                    "playback_complete": None,
                }
                rows.append(row)
                print(
                    f"{row['id']}: {row['seconds']}s, calls={dialogue.calls}, error={error}",
                    flush=True,
                )
    finally:
        if sdk:
            await sdk.close()
        if remote_decision:
            await remote_decision.aclose()
    confusion = {key: 0 for key in ("tp", "fp", "tn", "fn")}
    for row in rows:
        if row["expected_escalation"] is not None:
            confusion[
                ("t" if row["expected_escalation"] == row["actual_escalation"] else "f")
                + ("p" if row["actual_escalation"] else "n")
            ] += 1
    traces = [
        trace
        for row in rows
        if row["category"] != "fault"
        for trace in row["decision_traces"]
    ]
    model_attempts = sum(trace["source"] in {"model", "fallback"} for trace in traces)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance(args.fixtures),
        "fixture_version": fixture["version"],
        "run_note": args.run_note,
        "persona_sha256": hashlib.sha256(
            config.character_config.persona_prompt.encode("utf-8")
        ).hexdigest(),
        "configuration": {
            "dialogue": args.dialogue,
            "model": (args.model or settings.dialogue.model) if sdk else None,
            "decision": args.decision,
            "decision_protocol_version": settings.decision.protocol_version,
            "context_version": settings.context_version,
            "coordination_protocol_version": 2,
            "memory": args.memory,
            "expression": args.expression,
            "temperature": 0,
            "max_tokens": 384,
            "safety": "always_on",
        },
        "metrics": {
            "safety_confusion": confusion,
            "errors": sum(row["error"] is not None for row in rows),
            "strategy_cases_checked": sum(
                row["strategy_expectations_met"] is not None for row in rows
            ),
            "strategy_mismatches": sum(
                row["strategy_expectations_met"] is False for row in rows
            ),
            "state_consistency": sum(row["state_repeat_consistent"] for row in rows)
            / len(rows),
            "latency_mean_seconds": round(
                sum(row["seconds"] for row in rows) / len(rows), 3
            ),
            "decision_model_attempts": model_attempts,
            "decision_model_valid_rate": sum(
                trace["source"] == "model" for trace in traces
            )
            / model_attempts
            if model_attempts
            else None,
            "decision_fallbacks": sum(
                trace["source"] == "fallback" for trace in traces
            ),
            "synthetic_fault_recovered": any(
                row["category"] == "fault"
                and not row["error"]
                and any(t["source"] == "fallback" for t in row["decision_traces"])
                for row in rows
            ),
        },
        "limitations": [
            "Synthetic provisional labels, not clinical validation",
            "No audio synthesis or playback measured",
            "Human model quality ratings pending",
            "Stub dialogue is not model evaluation",
        ],
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "tests/fixtures/mental_health_cases.json",
    )
    parser.add_argument("--dialogue", choices=["stub", "model"], default="stub")
    parser.add_argument("--run-note", default="Uncontrolled local development run")
    parser.add_argument(
        "--model", help="Served dialogue model ID; no credentials in arguments"
    )
    parser.add_argument("--decision", choices=["rules", "model"], default="rules")
    parser.add_argument("--memory", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--expression", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "logs/evaluation/baseline.json"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new report path; existing results are immutable")
    logger.remove()
    try:
        report = asyncio.run(evaluate(args))
    except Exception as error:
        print(f"Evaluation setup failed ({type(error).__name__})")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return (
        1
        if report["metrics"]["errors"] or report["metrics"]["strategy_mismatches"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
