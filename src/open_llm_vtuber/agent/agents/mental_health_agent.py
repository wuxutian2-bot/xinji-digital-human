"""Conversation agent backed by the fine-tuned mental health dialogue model."""

from collections.abc import AsyncIterator
from typing import Literal
import re
import sqlite3
from uuid import uuid4

from loguru import logger

from ...config_manager import TTSPreprocessorConfig
from ...mental_health.dialogue_client import DialogueClient
from ...mental_health.intent_estimator import IntentEstimator, format_intent_context
from ...mental_health.decision_coordinator import coordinate_decision
from ...mental_health.context_signals import (
    protocol_boundary,
    protocol_redirect,
    sanitize_model_messages,
)
from ...mental_health.decision_client import (
    constrain_expression,
    format_decision_context,
)
from ...mental_health.interfaces import (
    DecisionClient,
    PsychologicalMemoryService,
    PsychologicalStateEstimator,
    SafetyGuard,
)
from ...mental_health.memory_service import format_memory_context
from ...mental_health.companion_store import companion_for, utc_now
from ...mental_health.long_term import trend_for_model
from ...mental_health.support_controls import MODES, resolve_support_intent
from ...mental_health.schemas import (
    DecisionCapabilities,
    DecisionContext,
    DecisionResult,
    DecisionTrace,
    SafetyAction,
    StrategyDecision,
    CoordinationTrace,
)
from ..input_types import BatchInput, TextSource
from ..output_types import Actions
from ..transformers import (
    display_processor,
    sentence_divider,
    tts_filter,
)
from .basic_memory_agent import BasicMemoryAgent


class MentalHealthAgent(BasicMemoryAgent):
    """Mental health Agent with mandatory safety and state-memory gates.

    The class has its own dialogue boundary while reusing the mature streaming,
    interruption, ordinary chat-memory, SentenceOutput, TTS, and Live2D behavior
    of ``BasicMemoryAgent``.
    """

    def __init__(
        self,
        dialogue_client: DialogueClient,
        decision_client: DecisionClient,
        safety_guard: SafetyGuard,
        state_estimator: PsychologicalStateEstimator,
        memory_service: PsychologicalMemoryService,
        system: str,
        live2d_model,
        tts_preprocessor_config: TTSPreprocessorConfig | None = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        interrupt_method: Literal["system", "user"] = "user",
        expression_enabled: bool = True,
        supported_voice_controls: frozenset[str] = frozenset(),
        behavior_frontend_enabled: bool = False,
        decision_protocol_version: Literal[1, 2] = 2,
    ) -> None:
        self._safety_guard = safety_guard
        self._decision_client = decision_client
        self._state_estimator = state_estimator
        self._psychological_memory = memory_service
        self.companion = companion_for(self)
        self.support_mode = None
        self._last_product_turn = None
        self._consumed_feedback = None
        self._psychological_memory_scope = f"session:{uuid4().hex}"
        self._intent_estimator = IntentEstimator()
        self._interaction_session = {"intent": None, "strategy": None}

        self._decision_protocol_version = decision_protocol_version
        self._expression_enabled = expression_enabled
        self._decision_capabilities = DecisionCapabilities(
            expressions=list(live2d_model.emo_map)
        )
        capabilities = getattr(live2d_model, "decision_capabilities", {})
        if behavior_frontend_enabled:
            self._decision_capabilities.motions = capabilities.get("motions", ["still"])
            self._decision_capabilities.gazes = capabilities.get("gazes", [])
            for field, values in (
                ("motion", self._decision_capabilities.motions),
                ("gaze", self._decision_capabilities.gazes),
            ):
                if values:
                    name = f"behavior.{field}"
                    self._decision_capabilities.applied_controls.append(name)
                    self._decision_capabilities.metadata_only_controls.remove(name)
        if "speed" in supported_voice_controls:
            self._decision_capabilities.applied_controls.append("voice.speed")
            self._decision_capabilities.metadata_only_controls.remove("voice.speed")
        if not expression_enabled:
            self._decision_capabilities.applied_controls = []
        super().__init__(
            llm=dialogue_client,
            system=system,
            live2d_model=live2d_model,
            tts_preprocessor_config=tts_preprocessor_config,
            faster_first_response=faster_first_response,
            segment_method=segment_method,
            use_mcpp=False,
            interrupt_method=interrupt_method,
        )

    def set_support_mode(self, mode):
        if mode is not None and mode not in MODES:
            raise ValueError("Unknown support preference")
        self.support_mode = mode
        self._interaction_session["intent"] = None

    def _pending_feedback(self):
        if not self.companion or not self._last_product_turn:
            return "unspecified"
        turn = self.companion.get("turn", self._last_product_turn)
        if not turn or turn.get("scope") != self._psychological_memory_scope:
            return "unspecified"
        marker = turn.get("feedback_updated_at")
        if marker and marker != self._consumed_feedback:
            self._consumed_feedback = marker
            return turn.get("feedback", "unspecified")
        return "unspecified"

    def _record_product_turn(
        self,
        input_data,
        record_id,
        state,
        decision,
        trend=None,
        *,
        scope=None,
        generation="completed",
    ):
        metadata = input_data.metadata or {}
        turn_id = metadata.get("companion_turn_id")
        if not self.companion or not turn_id:
            return
        invalidated = bool(
            (self.companion.get("turn", turn_id) or {}).get("history_invalidated")
        )
        self.companion.put(
            "turn",
            turn_id,
            {
                "id": turn_id,
                "timestamp": utc_now(),
                "record_id": record_id,
                "scope": scope or self._psychological_memory_scope,
                "synthetic": bool(metadata.get("synthetic_demo", False)),
                "intent": state.interaction_intent.model_dump(mode="json"),
                "history_context": trend_for_model(trend.model_dump(mode="json"))
                if trend and not invalidated
                else None,
                "history_invalidated": invalidated,
                "trace": state.decision_trace.model_dump(mode="json"),
                "final_strategy": decision.strategy.primary,
                "requested_expression": decision.behavior.model_dump(mode="json"),
                "requested_voice": decision.voice.model_dump(mode="json"),
                "support_mode": self.support_mode,
                "feedback": "unspecified",
                "playback": "unconfirmed",
                "generation": generation,
                "sent_segments": [],
            },
        )
        self._last_product_turn = turn_id

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load chat history and select a separate psychological-memory scope."""
        super().set_memory_from_history(conf_uid, history_uid)
        self._psychological_memory_scope = f"{conf_uid}:{history_uid}"
        self._interaction_session = {"intent": None, "strategy": None}
        self.support_mode = None
        self._last_product_turn = None
        self._consumed_feedback = None

    async def _load_recent_state(self, scope: str):
        try:
            return await self._psychological_memory.retrieve_recent(scope)
        except (OSError, ValueError, sqlite3.Error) as error:
            logger.error(
                "Failed to read psychological state memory ({})", type(error).__name__
            )
            return []

    async def _store_state(self, scope: str, state) -> None:
        try:
            return await self._psychological_memory.append(scope, state)
        except (OSError, ValueError, sqlite3.Error) as error:
            logger.error(
                "Failed to store psychological state memory ({})", type(error).__name__
            )

    def _remember_interaction(self, scope, session, intent, strategy, safety=None):
        # Tracks completed safe generation, not browser playback or user satisfaction.
        if (
            session is self._interaction_session
            and scope == self._psychological_memory_scope
        ):
            session["intent"] = None if strategy == "close_supportively" else intent
            session["strategy"] = strategy
            if safety is not None:
                session["safety"] = safety.model_copy(deep=True)

    def _chat_function_factory(self):
        """Create a pipeline with non-optional safety gates around generation."""

        @sentence_divider(
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            valid_tags=["think"],
        )
        async def chat_with_safety(
            input_data: BatchInput, decision_holder: dict[str, DecisionResult]
        ) -> AsyncIterator[str]:
            self.reset_interrupt()
            self.prompt_mode_flag = False
            scope = self._psychological_memory_scope
            session = self._interaction_session

            user_text = self._to_text_prompt(input_data)
            messages = self._to_messages(input_data)

            # Mandatory pre-generation gate.
            if hasattr(self._safety_guard, "check_input_with_context"):
                pre_check = await self._safety_guard.check_input_with_context(
                    user_text, session.get("safety")
                )
            else:
                pre_check = await self._safety_guard.check_input(user_text)
            boundary = protocol_boundary(user_text)
            intent_text = "\n".join(
                item.content
                for item in input_data.texts
                if item.source == TextSource.INPUT
            )
            current_state = await self._state_estimator.estimate(intent_text, pre_check)
            intent = self._intent_estimator.estimate(intent_text, session["intent"])
            intent, selected_mode = resolve_support_intent(
                intent, self.support_mode, self._pending_feedback()
            )
            if session is self._interaction_session:
                self.support_mode = selected_mode
            current_state.interaction_intent = intent

            if pre_check.action == SafetyAction.ESCALATE:
                decision_holder["value"] = DecisionResult(
                    strategy=StrategyDecision(primary="crisis_support")
                )
                response = pre_check.safe_response or (
                    "你的安全非常重要。请立即联系当地急救服务或可信任的人。"
                )
                current_state.decision_trace = DecisionTrace(
                    source="safety_gate",
                    protocol_version=self._decision_protocol_version,
                    coordination=CoordinationTrace(
                        proposed_strategy="crisis_support",
                        final_strategy="crisis_support",
                        previous_strategy=session["strategy"],
                        reason_codes=["safety_priority"],
                    ),
                )
                self._add_message(response, "assistant")
                record_id = await self._store_state(scope, current_state)
                self._record_product_turn(
                    input_data,
                    record_id,
                    current_state,
                    decision_holder["value"],
                    scope=scope,
                )
                self._remember_interaction(
                    scope, session, intent, "crisis_support", pre_check
                )
                yield response
                return

            recent_states = await self._load_recent_state(scope)
            trend = None
            if hasattr(self._psychological_memory, "retrieve_trend"):
                try:
                    trend = await self._psychological_memory.retrieve_trend()
                except (OSError, ValueError, sqlite3.Error) as error:
                    logger.warning(
                        "Long-term summary unavailable ({})", type(error).__name__
                    )
            context = DecisionContext(
                user_text=boundary.model_text,
                protocol_control_detected=boundary.detected,
                current_state=current_state,
                recent_states=recent_states,
                safety=pre_check,
                capabilities=self._decision_capabilities,
                long_term_trend=trend.model_dump() if trend is not None else None,
                interaction_intent=intent,
                previous_strategy=session["strategy"],
            )
            decision = constrain_expression(
                coordinate_decision(
                    await self._decision_client.decide(context), context
                ),
                context,
            )
            decision.trace.protocol_version = self._decision_protocol_version
            decision_holder["value"] = decision
            current_state.interaction_strategy = decision.strategy.primary
            current_state.decision_trace = decision.trace.model_copy(deep=True)
            self._record_product_turn(
                input_data,
                None,
                current_state,
                decision,
                trend,
                scope=scope,
                generation="pending",
            )

            contextual_system = (
                f"{self._system}\n\n"
                f"{format_memory_context(current_state, recent_states, trend)}\n\n"
                f"{format_intent_context(intent, context.previous_strategy)}\n\n"
                f"{format_decision_context(decision)}"
            )
            if pre_check.action == SafetyAction.SUPPORT:
                contextual_system += (
                    "\nThe current message contains elevated distress language. "
                    "Respond calmly, validate feelings, check immediate safety, and "
                    "encourage appropriate human support without making a diagnosis."
                )

            token_stream = self._llm.chat_completion(
                sanitize_model_messages(messages), contextual_system
            )
            generated_response = ""
            async for event in token_stream:
                if isinstance(event, str):
                    generated_response += event
                elif isinstance(event, dict) and event.get("type") == "text_delta":
                    generated_response += event.get("text", "")

            # Mandatory post-generation gate. No generated text is yielded before it.
            post_check = await self._safety_guard.check_output(generated_response)
            response = post_check.safe_response or generated_response
            if post_check.action in {SafetyAction.BLOCK, SafetyAction.REWRITE}:
                decision_holder["value"] = DecisionResult()
                decision.trace.output_safety_override = True
                decision.trace.coordination.final_strategy = decision_holder[
                    "value"
                ].strategy.primary
                decision.trace.coordination.reason_codes.append(
                    "output_safety_override"
                )
            elif boundary.control_only and not input_data.images:
                # A local product boundary, distinct from harm/diagnosis filtering.
                # Keep the model proposal and source; record who supplied final text.
                response = protocol_redirect(
                    user_text, intent.advice_preference == "declined"
                )
                decision_holder["value"] = DecisionResult()
                decision.trace.coordination.final_strategy = "supportive_listening"
                decision.trace.output_policy_override = True
                decision.trace.coordination.reason_codes.append(
                    "protocol_boundary_response"
                )
            # Legacy dialogue tags never control the avatar in this agent.
            for expression in self._live2d_model.emo_map:
                response = re.sub(
                    r"\[" + re.escape(expression) + r"\]", "", response, flags=re.I
                )
            current_state.interaction_strategy = decision_holder[
                "value"
            ].strategy.primary
            current_state.decision_trace = decision.trace.model_copy(deep=True)
            self._add_message(response, "assistant")
            record_id = await self._store_state(scope, current_state)
            self._record_product_turn(
                input_data,
                record_id,
                current_state,
                decision_holder["value"],
                trend,
                scope=scope,
            )
            self._remember_interaction(
                scope, session, intent, current_state.interaction_strategy, pre_check
            )
            yield response

        @tts_filter(self._tts_preprocessor_config)
        @display_processor()
        async def chat_with_decision_actions(input_data: BatchInput):
            # Per invocation: overlapping generators must not share decisions.
            decision_holder = {"value": DecisionResult()}
            first_sentence = True
            async for sentence in chat_with_safety(input_data, decision_holder):
                decision = decision_holder["value"]
                if not self._expression_enabled:
                    yield sentence, Actions()
                    continue
                actions = Actions(
                    voice_style=decision.voice.style,
                    voice_speed=decision.voice.speed,
                    voice_energy=decision.voice.energy,
                )
                if first_sentence:
                    expression = self._live2d_model.emo_map.get(
                        decision.behavior.expression.lower(),
                        self._live2d_model.emo_map.get("neutral"),
                    )
                    if expression is not None:
                        actions.expressions = [expression]
                    actions.motion = decision.behavior.motion
                    actions.gaze = decision.behavior.gaze
                    actions.strategy = decision.strategy.model_dump()
                    first_sentence = False
                yield sentence, actions

        return chat_with_decision_actions
