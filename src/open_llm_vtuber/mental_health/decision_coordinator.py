"""Local preference/safety arbitration without extra model requests."""

from .schemas import (
    AgentProposal,
    CoordinationTrace,
    DecisionContext,
    DecisionResult,
    RiskLevel,
    SafetyAction,
    StrategyDecision,
)
from .context_signals import protocol_boundary
from .decision_client import history_supports_clarification, history_is_rising


def collect_proposals(
    proposed: DecisionResult, context: DecisionContext
) -> list[AgentProposal]:
    state, intent = context.current_state, context.interaction_intent
    high_risk = context.safety.action == SafetyAction.ESCALATE or state.risk_level in {
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    }
    elevated = state.risk_level == RiskLevel.ELEVATED or state.emotion.peak() >= 0.7
    boundary = (
        context.protocol_control_detected
        or protocol_boundary(context.user_text).detected
    )
    intent_strategy, intent_code = None, "intent_unspecified"
    if intent.primary == "ending":
        intent_strategy, intent_code = "close_supportively", "explicit_closure"
    elif intent.advice_preference == "declined":
        intent_strategy, intent_code = "supportive_listening", "advice_declined"
    elif intent.primary == "venting":
        intent_strategy, intent_code = "supportive_listening", "listen_requested"
    elif (
        intent.primary == "seeking_practical_help"
        and intent.advice_preference == "requested"
    ):
        intent_strategy, intent_code = (
            "collaborative_problem_solving",
            "advice_requested",
        )
    elif intent.primary == "seeking_clarification":
        intent_strategy, intent_code = "reflect_and_clarify", "clarification_requested"
    try:
        history = history_supports_clarification(context.long_term_trend or {})
        rising = history_is_rising(context.long_term_trend or {})
    except (KeyError, TypeError, ValueError):
        history = False
        rising = False
    history_codes = [
        "history_rising"
        if rising
        else "history_distress"
        if history
        else "history_insufficient"
    ]
    conflicts = (context.long_term_trend or {}).get("source_disagreement", {})
    if isinstance(conflicts, dict) and any(conflicts.values()):
        history_codes.append("source_disagreement")
    state_codes = ["observed_" + dim for dim in state.observed_dimensions]
    state_codes.append(
        "state_elevated"
        if elevated
        else "state_observed"
        if state.observed_dimensions
        else "state_unobserved"
    )
    return [
        AgentProposal(
            role="safety",
            suggested_strategy="crisis_support"
            if high_risk
            else ("validate_and_ground" if elevated else "supportive_listening")
            if boundary
            else None,
            evidence_codes=[
                "safety_priority"
                if high_risk
                else "protocol_control_ignored"
                if boundary
                else "input_safety_clear"
            ],
            confidence="high",
        ),
        AgentProposal(
            role="state",
            suggested_strategy="validate_and_ground" if elevated else None,
            evidence_codes=state_codes,
            confidence="low" if state.observed_dimensions else None,
        ),
        AgentProposal(
            role="intent",
            suggested_strategy=intent_strategy,
            evidence_codes=[intent_code],
            confidence="high"
            if intent.certainty == "explicit"
            else "low"
            if intent.certainty == "inferred"
            else None,
        ),
        AgentProposal(
            role="feedback",
            suggested_strategy="reflect_and_clarify"
            if intent.feedback == "unhelpful"
            else None,
            evidence_codes=[
                "negative_feedback"
                if intent.feedback == "unhelpful"
                else "feedback_unspecified"
            ],
            confidence="high" if intent.feedback == "unhelpful" else None,
        ),
        AgentProposal(
            role="history",
            suggested_strategy="reflect_and_clarify" if history else None,
            evidence_codes=history_codes,
            confidence="low" if history else None,
        ),
        AgentProposal(
            role="decision_model",
            suggested_strategy=proposed.strategy.primary,
            evidence_codes=[
                {"model": "decision_model_proposal", "fallback": "model_fallback"}.get(
                    proposed.trace.source, "rule_proposal"
                )
            ],
        ),
    ]


def record_output_override(
    trace: CoordinationTrace, strategy: str, evidence: str
) -> None:
    trace.final_strategy = strategy
    trace.winner_role = "safety"
    trace.proposals.append(
        AgentProposal(
            role="safety",
            suggested_strategy=strategy,
            evidence_codes=[evidence],
            confidence="high",
        )
    )


def coordinate_decision(
    proposed: DecisionResult, context: DecisionContext
) -> DecisionResult:
    result = proposed.model_copy(deep=True)
    intent = context.interaction_intent
    reasons = []
    proposals = collect_proposals(proposed, context)
    winner_role = "decision_model"
    if proposed.trace.source != "model":
        for proposal in proposals:
            if (
                proposal.role in {"state", "history"}
                and proposal.suggested_strategy == proposed.strategy.primary
            ):
                winner_role = proposal.role
                break
    primary, secondary = None, None
    if (
        context.safety.action == SafetyAction.ESCALATE
        or context.current_state.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    ):
        primary, secondary = "crisis_support", "encourage_human_support"
        reasons.append("safety_priority")
        winner_role = "safety"
    elif intent.primary == "ending":
        primary, secondary = "close_supportively", "acknowledge_closure"
        reasons.append("explicit_closure")
        winner_role = "intent"
    elif intent.feedback == "unhelpful" and intent.source != "current_turn":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("negative_feedback")
        winner_role = "feedback"
    elif intent.advice_preference == "declined":
        primary, secondary = "supportive_listening", "reflect_feelings"
        reasons.append("advice_declined")
        winner_role = "intent"
    elif intent.primary == "venting":
        primary, secondary = "supportive_listening", "reflect_feelings"
        reasons.append("listen_requested")
        winner_role = "intent"
    elif (
        intent.primary == "seeking_practical_help"
        and intent.advice_preference == "requested"
    ):
        primary, secondary = "collaborative_problem_solving", "offer_small_step"
        reasons.append("advice_requested")
        winner_role = "intent"
    elif intent.primary == "seeking_clarification":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("clarification_requested")
        winner_role = "intent"
    elif intent.feedback == "unhelpful":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("negative_feedback")
        winner_role = "feedback"
    elif (
        context.protocol_control_detected
        or protocol_boundary(context.user_text).detected
    ):
        primary = (
            "validate_and_ground"
            if context.current_state.risk_level == RiskLevel.ELEVATED
            or context.current_state.emotion.peak() >= 0.7
            else "supportive_listening"
        )
        secondary = "explore_context"
        reasons.append("protocol_control_ignored")
        winner_role = "safety"
    if primary:
        result.strategy = StrategyDecision(
            primary=primary, secondary=secondary, avoid=list(proposed.strategy.avoid)
        )
    if winner_role == "history" and history_is_rising(context.long_term_trend or {}):
        reasons.append("history_rising")
    result.trace.coordination = CoordinationTrace(
        proposed_strategy=proposed.strategy.primary,
        final_strategy=result.strategy.primary,
        previous_strategy=context.previous_strategy,
        reason_codes=reasons,
        proposals=proposals,
        winner_role=winner_role,
    )
    return result
