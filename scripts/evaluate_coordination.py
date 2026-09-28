"""Frozen R0-R4 experiment through the production Agent, using synthetic data only."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import socket
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from loguru import logger  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from evaluate_mental_health import provenance, UnavailableDecision  # noqa: E402
from open_llm_vtuber.agent.agents.mental_health_agent import MentalHealthAgent  # noqa: E402
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource  # noqa: E402
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402
from open_llm_vtuber.mental_health.context_safety import ContextSafetyGuard  # noqa: E402
from open_llm_vtuber.mental_health.context_state import ContextStateEstimator  # noqa: E402
from open_llm_vtuber.mental_health.decision_client import (  # noqa: E402
    FallbackDecisionClient,
    OpenAICompatibleDecisionClient,
    RuleBasedDecisionClient,
)
from open_llm_vtuber.mental_health.dialogue_client import DialogueClient  # noqa: E402
from open_llm_vtuber.mental_health.long_term import TrendSettings  # noqa: E402
from open_llm_vtuber.mental_health.schemas import (  # noqa: E402
    DecisionContext,
    PsychologicalState,
    InteractionIntent,
    SafetyCheckResult,
)
from open_llm_vtuber.mental_health.sqlite_memory import SqlitePsychologicalMemoryService  # noqa: E402

GROUPS = {
    "R0": {"decision": "rules", "intent": True, "memory": True, "trend": "daily_v2"},
    "R1": {"decision": "model", "intent": True, "memory": True, "trend": "daily_v2"},
    "R2": {"decision": "model", "intent": False, "memory": True, "trend": "daily_v2"},
    "R3": {"decision": "model", "intent": True, "memory": False, "trend": None},
    "R4": {"decision": "model", "intent": True, "memory": True, "trend": "rolling_v1"},
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def read_settings(path):
    return Config.model_validate(read_yaml(str(path)))


def load_fixtures(path):
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    now = datetime.fromisoformat(fixture["as_of"])
    if now.tzinfo is None:
        raise ValueError("Fixture reference timestamp must have a timezone")
    seen, families = set(), {"development": set(), "holdout": set()}
    if not fixture["cases"]:
        raise ValueError("Empty fixture")
    for case in fixture["cases"]:
        if case["id"] in seen or case["split"] not in families or not case["turns"]:
            raise ValueError("Duplicate case or invalid split/turns")
        seen.add(case["id"])
        families[case["split"]].add(case["family"])
        for turn in case["turns"]:
            if not turn["text"].strip() or not isinstance(
                turn["expect_escalation"], bool
            ):
                raise ValueError("Each turn needs text and a provisional Safety label")
        for historic in case.get("history", []):
            if (
                not 1 <= historic.get("repeat", 1) <= 100
                or not 1 <= historic["days_ago"] <= 365
            ):
                raise ValueError("Invalid synthetic history")
    if families["development"] & families["holdout"]:
        raise ValueError("Development and holdout families must be disjoint")
    return fixture


def make_schedule(cases, repeats, seed):
    if repeats < 1:
        raise ValueError("At least one repeat required")
    rng, schedule = random.Random(seed), []
    for repeat in range(1, repeats + 1):
        order = list(cases)
        rng.shuffle(order)
        for case in order:
            groups = list(GROUPS)
            rng.shuffle(groups)
            schedule.extend(
                {"group": group, "repeat": repeat, "case_id": case["id"]}
                for group in groups
            )
    return schedule


class Meter:
    """Measure SDK calls with retries disabled; records raw completions, not credentials."""

    def __init__(self, sdk, kind, seed=None):
        self.sdk, self.kind, self.seed = sdk, kind, seed
        self.calls = []

    async def create(self, **kwargs):
        if self.seed is not None:
            kwargs["seed"] = self.seed
        row = {
            "kind": self.kind,
            "seed_requested": self.seed,
            "error": None,
            "request_sha256": hashlib.sha256(
                json.dumps(kwargs, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
            "prompt_sha256": hashlib.sha256(
                kwargs["messages"][0]["content"].encode()
            ).hexdigest(),
            "finish_reason": None,
            "usage": None,
            "response_model": None,
            "raw_text": None,
        }
        self.calls.append(row)
        started = perf_counter()
        try:
            result = await self.sdk.chat.completions.create(**kwargs)
            row.update(
                response_model=result.model,
                usage=result.usage.model_dump() if result.usage else None,
                system_fingerprint=getattr(result, "system_fingerprint", None),
            )
            if result.choices:
                row.update(
                    finish_reason=result.choices[0].finish_reason,
                    raw_text=result.choices[0].message.content or "",
                )
                row["output_chars"] = len(row["raw_text"])
            return result
        except BaseException as error:
            row["error"] = type(error).__name__
            raise
        finally:
            row["seconds"] = round(perf_counter() - started, 4)


class Dialogue:
    def __init__(self, meter, model, dry_run):
        self.meter, self.model, self.dry_run = meter, model, dry_run

    async def chat_completion(self, messages, system=None, tools=None):
        if self.dry_run:
            yield "我听到了你的感受，愿意陪你聊聊。"
            return
        result = await asyncio.wait_for(
            self.meter.create(
                model=self.model,
                messages=[{"role": "system", "content": system}]
                + DialogueClient._merge_adjacent_turns(messages),
                temperature=0,
                max_tokens=384,
                stream=False,
            ),
            timeout=60,
        )
        if not result.choices:
            raise ValueError("Empty Dialogue choices")
        yield result.choices[0].message.content or ""


class CaptureSafety(ContextSafetyGuard):
    def __init__(self):
        self.pre, self.post = [], []

    async def check_input_with_context(self, text, previous=None):
        result = await super().check_input_with_context(text, previous)
        self.pre.append(result.model_dump(mode="json"))
        return result

    async def check_output(self, text):
        result = await super().check_output(text)
        self.post.append(result.model_dump(mode="json"))
        return result


class FrozenEstimator(ContextStateEstimator):
    def __init__(self, memory):
        self.memory = memory

    async def estimate(self, text, safety):
        state = await super().estimate(text, safety)
        state.timestamp = self.memory.now
        return state


class UnknownIntent:
    def estimate(self, text, previous=None):
        return InteractionIntent()


class CaptureMemory:
    """Real SQLite; R3 writes traces but never reads state into the pipeline."""

    def __init__(self, store, now, enabled):
        self.store, self.now, self.enabled = store, now, enabled
        self.saved, self.trend = [], None

    async def append(self, scope, state):
        await self.store.append(scope, state)
        self.saved.append(state.model_copy(deep=True))

    async def retrieve_recent(self, scope):
        return await self.store.retrieve_recent(scope) if self.enabled else []

    async def retrieve_trend(self):
        self.trend = await self.store.retrieve_trend(self.now) if self.enabled else None
        return self.trend


class CaptureDecision:
    def __init__(self, client):
        self.client, self.contexts, self.proposals = client, [], []

    async def decide(self, context):
        self.contexts.append(context.model_dump(mode="json"))
        result = await self.client.decide(context)
        self.proposals.append(result.model_dump(mode="json"))
        return result


def remote_client(config, meter):
    kwargs = config.character_config.agent_config.agent_settings.mental_health_agent.decision.model_dump(
        exclude={"enabled"}
    )
    kwargs.update(
        temperature=0,
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=meter.create))
        ),
    )
    return OpenAICompatibleDecisionClient(**kwargs)


async def run_case(
    config, case, group, as_of, dialogue_sdk, decision_sdk, *, dry_run=False
):
    variant = GROUPS[group]
    settings = config.character_config.agent_config.agent_settings.mental_health_agent
    now = datetime.fromisoformat(as_of)
    dialogue_meter, decision_meter = (
        Meter(dialogue_sdk, "dialogue"),
        Meter(decision_sdk, "decision", 20260923),
    )
    with TemporaryDirectory() as temp:
        store = SqlitePsychologicalMemoryService(
            str(Path(temp) / "synthetic.db"),
            "synthetic-only",
            recent_limit=5,
            trend_settings=TrendSettings(
                version=variant["trend"] or "daily_v2", timezone="Asia/Shanghai"
            ),
        )
        for historic in case.get("history", []):
            for number in range(historic.get("repeat", 1)):
                await store.append(
                    "synthetic-history",
                    PsychologicalState(
                        timestamp=now
                        - timedelta(days=historic["days_ago"], minutes=number),
                        schema_version=3,
                        estimator_source="context_v2",
                        confidence="low",
                        observed_dimensions=["stress"],
                        emotion={"stress": historic["stress"]},
                        topics=["work"],
                    ),
                )
        memory = CaptureMemory(store, now, variant["memory"])
        guard = CaptureSafety()
        primary = (
            RuleBasedDecisionClient()
            if dry_run or variant["decision"] == "rules"
            else remote_client(config, decision_meter)
        )
        # Synthetic outage is deliberately not counted as an actual model request.
        decision = CaptureDecision(
            FallbackDecisionClient(UnavailableDecision())
            if case.get("decision_failure")
            else FallbackDecisionClient(primary)
            if variant["decision"] == "model"
            else primary
        )
        agent = MentalHealthAgent(
            dialogue_client=Dialogue(dialogue_meter, settings.dialogue.model, dry_run),
            decision_client=decision,
            safety_guard=guard,
            state_estimator=FrozenEstimator(memory),
            memory_service=memory,
            system=config.character_config.persona_prompt,
            live2d_model=SimpleNamespace(
                emo_map={"neutral": 0, "sadness": 1, "fear": 1, "joy": 3}
            ),
            tts_preprocessor_config=config.character_config.tts_preprocessor_config,
            faster_first_response=False,
            segment_method="regex",
            expression_enabled=True,
            decision_protocol_version=2,
        )
        if not variant["intent"]:
            agent._intent_estimator = (
                UnknownIntent()
            )  # Offline ablation only, never a live config switch.
        rows = []
        for index, turn in enumerate(case["turns"], 1):
            before_d, before_l = len(decision_meter.calls), len(dialogue_meter.calls)
            before_p, before_c, before_s = (
                len(guard.post),
                len(decision.contexts),
                len(memory.saved),
            )
            outputs, error = [], None
            started = perf_counter()
            try:
                outputs = [
                    item
                    async for item in agent.chat(
                        BatchInput(
                            texts=[
                                TextData(source=TextSource.INPUT, content=turn["text"])
                            ]
                        )
                    )
                ]
            except Exception as caught:
                error = type(caught).__name__
            elapsed = round(perf_counter() - started, 4)
            saved = memory.saved[-1] if len(memory.saved) > before_s else None
            trace = (
                saved.decision_trace.model_dump(mode="json")
                if saved and saved.decision_trace
                else None
            )
            final = (
                trace["coordination"]["final_strategy"]
                if trace and trace["coordination"]
                else None
            )
            prior = rows[-1]["final_strategy"] if rows else None
            row = {
                "turn": index,
                "input": turn["text"],
                "response": "".join(item.display_text.text for item in outputs),
                "expected_strategy": turn["expected_strategy"],
                "expected_escalation": turn["expect_escalation"],
                "declines_advice": turn.get("declines_advice", False),
                "final_strategy": final,
                "strategy_match": final == turn["expected_strategy"]
                if turn["expected_strategy"]
                else None,
                "repeated_strategy": final == prior if prior and final else None,
                "strategy_repeat_is_not_quality_failure": True,
                "pre_safety": guard.pre[-1] if guard.pre else None,
                "post_safety": guard.post[-1] if len(guard.post) > before_p else None,
                "state": saved.model_dump(mode="json") if saved else None,
                "intent": saved.interaction_intent.model_dump(mode="json")
                if saved and saved.interaction_intent
                else None,
                "trend": memory.trend.model_dump(mode="json")
                if memory.trend is not None
                else None,
                "decision_context": decision.contexts[-1]
                if len(decision.contexts) > before_c
                else None,
                "proposal": decision.proposals[-1]
                if len(decision.contexts) > before_c and decision.proposals
                else None,
                "decision_trace": trace,
                "api_calls": [
                    *decision_meter.calls[before_d:],
                    *dialogue_meter.calls[before_l:],
                ],
                "actions": [item.actions.to_dict() for item in outputs],
                "execution": {
                    "parameters_emitted": bool(outputs),
                    "tts_synthesized": False,
                    "browser_executed": False,
                },
                "playback_complete": None,
                "seconds": elapsed,
                "error": error,
                "human_ratings": {
                    "supportiveness": None,
                    "coherence": None,
                    "intent_fit": None,
                    "unsupported_diagnosis": None,
                    "preference_violation": None,
                    "evidence": None,
                },
            }
            rows.append(row)
            memory.now += timedelta(seconds=1)
        return rows


def aggregate(runs):
    result = {}
    for group in GROUPS:
        selected = [run for run in runs if run["group"] == group]
        sections = {}
        for category in ("ordinary", "fault"):
            rows = [
                row
                for run in selected
                if (run["category"] == "fault") == (category == "fault")
                for row in run["turns"]
            ]
            calls = [call for row in rows for call in row["api_calls"]]
            traces = [row["decision_trace"] for row in rows if row["decision_trace"]]
            model = [call for call in calls if call["kind"] == "decision"]
            escalation = [
                row
                for row in rows
                if row["pre_safety"] and row["pre_safety"]["action"] == "escalate"
            ]
            sections[category] = {
                "turns": len(rows),
                "errors": sum(row["error"] is not None for row in rows),
                "strategy_checked": sum(
                    row["strategy_match"] is not None for row in rows
                ),
                "strategy_mismatches": sum(
                    row["strategy_match"] is False for row in rows
                ),
                "decision_http_attempts": len(model),
                "dialogue_http_attempts": sum(
                    call["kind"] == "dialogue" for call in calls
                ),
                "model_valid_decisions": sum(
                    trace["source"] == "model" for trace in traces
                ),
                "fallbacks": sum(trace["source"] == "fallback" for trace in traces),
                "rules": sum(trace["source"] == "rules" for trace in traces),
                "safety_gate": sum(
                    trace["source"] == "safety_gate" for trace in traces
                ),
                "safety_mismatches": sum(
                    (row["pre_safety"]["action"] == "escalate")
                    != row["expected_escalation"]
                    for row in rows
                    if row["pre_safety"]
                ),
                "safety_bypass_http_attempts": sum(
                    len(row["api_calls"]) for row in escalation
                ),
                "output_safety_overrides": sum(
                    trace["output_safety_override"] for trace in traces
                ),
                "output_policy_overrides": sum(
                    trace["output_policy_override"] for trace in traces
                ),
                "truncated_calls": sum(
                    call["finish_reason"] == "length" for call in calls
                ),
                "sdk_errors": sum(call["error"] is not None for call in calls),
                "declined_advice_strategy_mismatches": sum(
                    row["declines_advice"]
                    and row["final_strategy"] != "supportive_listening"
                    for row in rows
                ),
                "repeated_strategy_count": sum(
                    row["repeated_strategy"] is True for row in rows
                ),
                "repeat_opportunities": sum(
                    row["repeated_strategy"] is not None for row in rows
                ),
                "full_turn_seconds": [row["seconds"] for row in rows],
                "decision_request_seconds": [call["seconds"] for call in model],
                "unsupported_diagnosis_human_count": None,
                "preference_violation_human_count": None,
            }
        result[group] = sections
    return result


async def verify_models(config, dialogue, decision):
    settings = config.character_config.agent_config.agent_settings.mental_health_agent
    for sdk, name in (
        (dialogue, settings.dialogue.model),
        (decision, settings.decision.model),
    ):
        models = await asyncio.wait_for(sdk.models.list(), 5)
        if name not in {model.id for model in models.data}:
            raise ValueError("Required model not advertised")


def ensure_web_stopped(config):
    try:
        with socket.create_connection(
            (config.system_config.host, config.system_config.port), timeout=1
        ):
            pass
    except OSError:
        return
    raise ValueError("Stop this project's web service during controlled evaluation")


def freeze(config, fixture_path, fixture, schedule, repeats, dry_run, order_seed):
    settings = config.character_config.agent_config.agent_settings.mental_health_agent
    prov = provenance(fixture_path)
    extra = [
        Path(__file__),
        ROOT / "scripts/export_coordination_trace.py",
        ROOT / "tests/test_coordination_evaluation.py",
    ]
    extra += list((ROOT / "src/open_llm_vtuber/agent").glob("*.py"))
    extra += [
        ROOT / "src/open_llm_vtuber/agent/agents/basic_memory_agent.py",
        ROOT / "src/open_llm_vtuber/utils/sentence_divider.py",
        ROOT / "src/open_llm_vtuber/utils/tts_preprocessor.py",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ]
    prov["source_sha256"].update(
        {path.relative_to(ROOT).as_posix(): digest(path) for path in extra}
    )
    artifacts = {}
    if not dry_run:
        adapter = "sft" if settings.dialogue.model == "mental-health-sft" else "orpo"
        template = ROOT / f"config_templates/mental_health_{adapter}_api.yaml"
        model_config = read_yaml(str(template))
        model_path, adapter_path = (
            Path(model_config["model_name_or_path"]),
            Path(model_config["adapter_name_or_path"]),
        )
        files = {
            "dialogue_template": template,
            "adapter_config": adapter_path / "adapter_config.json",
            "adapter_weights": adapter_path / "adapter_model.safetensors",
            "decision_weights": ROOT
            / "models/decision/qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "decision_executable": ROOT
            / "private/decision/llama-b10964-cpu/llama-server.exe",
            "decision_deployment_manifest": ROOT
            / "private/decision/deployment-cpu.json",
        }
        files.update(
            {
                "base_" + path.name: path
                for path in sorted(model_path.glob("*.safetensors"))
            }
        )
        files.update(
            {
                "base_" + name: model_path / name
                for name in ("config.json", "tokenizer_config.json")
            }
        )
        artifacts = {
            name: {"sha256": digest(path), "bytes": path.stat().st_size}
            for name, path in files.items()
        }
    return {
        "schema_version": 1,
        "dry_run": dry_run,
        "as_of": fixture["as_of"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": prov,
        "persona_sha256": hashlib.sha256(
            config.character_config.persona_prompt.encode()
        ).hexdigest(),
        "model_artifacts": artifacts,
        "groups": GROUPS,
        "repeats": repeats,
        "order_seed": order_seed,
        "schedule": schedule,
        "fixtures": fixture,
        "configuration": {
            "safety": "always_on",
            "context_version": 2,
            "protocol_version": 2,
            "dialogue_model": settings.dialogue.model,
            "dialogue_temperature": 0,
            "dialogue_max_tokens": 384,
            "decision_model": settings.decision.model,
            "decision_temperature": 0,
            "decision_max_tokens": settings.decision.max_tokens,
            "decision_response_format": settings.decision.response_format,
            "decision_timeout_seconds": settings.decision.timeout_seconds,
            "trend": TrendSettings(version="daily_v2").model_dump(),
            "decision_seed_requested": 20260923,
            "dialogue_seed_requested": None,
            "seed_limit": "Decision request seed only; Dialogue service has no verified seed support. No bitwise determinism claim.",
            "sdk_retries": 0,
            "expression_parameters": True,
            "playback": False,
        },
        "timing": "turn seconds: Agent entry through final state persistence and text/Actions collection; request seconds: SDK create await; excludes setup, warmup, report writing, TTS and playback",
        "limitations": [
            "Small synthetic developer-labeled suite; holdout is not independently or clinically labeled",
            "R2 replaces structured intent by unknown but raw conversation remains visible to both models",
            "R4 changes the complete history representation including record-weighted recent context; not a pure mean-formula intervention",
            "R3 disables reads of structured psychological memory; within-conversation raw chat still exists",
            "Repeated outputs and strategy matches are not human quality or clinical outcome scores",
            "No tuning after freeze; report failures and truncation without replacing runs",
        ],
    }


async def experiment(args):
    if args.output_dir.exists():
        raise FileExistsError("Choose a new experiment directory")
    if args.repeats < (1 if args.dry_run else 3):
        raise ValueError("Real experiments require at least three repeats")
    config, fixture = read_settings(args.config), load_fixtures(args.fixtures)
    settings = config.character_config.agent_config.agent_settings.mental_health_agent
    if not args.dry_run and (
        settings.context_version != 2
        or settings.decision.protocol_version != 2
        or not settings.decision.enabled
    ):
        raise ValueError(
            "Explicit context v2 / Decision protocol v2 / independent API config required"
        )
    schedule = make_schedule(fixture["cases"], args.repeats, args.order_seed)
    dialogue, decision = None, None
    if not args.dry_run:
        for url in (settings.dialogue.base_url, settings.decision.base_url):
            if urlsplit(url).hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError(
                    "This synthetic runner requires dedicated local endpoints"
                )
        ensure_web_stopped(config)
        dialogue = AsyncOpenAI(
            base_url=settings.dialogue.base_url,
            api_key=settings.dialogue.llm_api_key,
            max_retries=0,
            timeout=60,
        )
        decision = AsyncOpenAI(
            base_url=settings.decision.base_url,
            api_key=settings.decision.llm_api_key,
            max_retries=0,
            timeout=settings.decision.timeout_seconds,
        )
    args.output_dir.mkdir(parents=True)
    runs, warmups = [], []
    manifest = freeze(
        config,
        args.fixtures,
        fixture,
        schedule,
        args.repeats,
        args.dry_run,
        args.order_seed,
    )
    write_new_json(args.output_dir / "manifest.json", manifest)
    write_new_json(args.output_dir / "fixtures.json", fixture)
    status, setup_error = "complete", None
    try:
        if not args.dry_run:
            await verify_models(config, dialogue, decision)
            # Equal exposure for both resident services before every group, including R0.
            for group in GROUPS:
                dm, lm = (
                    Meter(decision, "decision", 20260923),
                    Meter(dialogue, "dialogue"),
                )
                warmup = {"group": group, "calls": []}
                warmups.append(warmup)
                # Keep even a failed warmup attempt in the final report.
                warmup["calls"] = dm.calls
                lm.calls = dm.calls
                await remote_client(config, dm).decide(
                    DecisionContext(
                        user_text="你好",
                        current_state=PsychologicalState(
                            timestamp=datetime.fromisoformat(fixture["as_of"])
                        ),
                        safety=SafetyCheckResult(action="allow"),
                    )
                )
                await lm.create(
                    model=settings.dialogue.model,
                    messages=[{"role": "user", "content": "你好，请简短回应。"}],
                    temperature=0,
                    max_tokens=32,
                    stream=False,
                )
            write_new_json(args.output_dir / "warmup.json", warmups)
        by_id = {case["id"]: case for case in fixture["cases"]}
        for index, item in enumerate(schedule, 1):
            case = by_id[item["case_id"]]
            turns = await run_case(
                config,
                case,
                item["group"],
                fixture["as_of"],
                dialogue,
                decision,
                dry_run=args.dry_run,
            )
            run = {
                **item,
                "split": case["split"],
                "category": case["category"],
                "turns": turns,
            }
            runs.append(run)
            write_new_json(args.output_dir / f"run-{index:03d}.json", run)
            print(
                f"{index}/{len(schedule)} {item['group']} repeat={item['repeat']} {case['id']} errors={sum(t['error'] is not None for t in turns)}",
                flush=True,
            )
        for name, expected in manifest["provenance"]["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("Source changed after freeze")
    except (Exception, asyncio.CancelledError) as error:
        setup_error = type(error).__name__
        status = "pending" if not runs else "partial"
    finally:
        if dialogue:
            await dialogue.close()
        if decision:
            await decision.close()
        report = {
            "status": status,
            "setup_error": setup_error,
            "manifest_sha256": digest(args.output_dir / "manifest.json"),
            "dry_run": args.dry_run,
            "warmup": warmups,
            "runs": runs,
            "metrics": aggregate(runs),
        }
        write_new_json(args.output_dir / "report.json", report)
    print(
        json.dumps(
            {
                "status": status,
                "runs": len(runs),
                "dry_run": args.dry_run,
                "setup_error": setup_error,
            }
        ),
        flush=True,
    )
    return 0 if status == "complete" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument(
        "--fixtures", type=Path, default=ROOT / "tests/fixtures/coordination_cases.json"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--order-seed", type=int, default=20260923)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Engineering checks only; never real model evidence",
    )
    args = parser.parse_args()
    logger.remove()
    try:
        return asyncio.run(experiment(args))
    except Exception as error:
        print(
            f"Setup rejected ({type(error).__name__}); inspect configuration and output paths"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
