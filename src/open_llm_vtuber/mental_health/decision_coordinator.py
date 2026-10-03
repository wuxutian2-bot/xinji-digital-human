"""Local preference/safety arbitration without extra model requests."""

from .schemas import (
    CoordinationTrace,
    DecisionContext,
    DecisionResult,
    RiskLevel,
    SafetyAction,
    StrategyDecision,
)
from .context_signals import protocol_boundary


def coordinate_decision(
    proposed: DecisionResult, context: DecisionContext
) -> DecisionResult:
    result = proposed.model_copy(deep=True)
    intent = context.interaction_intent
    reasons = []
    primary, secondary = None, None
    if (
        context.safety.action == SafetyAction.ESCALATE
        or context.current_state.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    ):
        primary, secondary = "crisis_support", "encourage_human_support"
        reasons.append("safety_priority")
    elif intent.primary == "ending":
        primary, secondary = "close_supportively", "acknowledge_closure"
        reasons.append("explicit_closure")
    elif intent.feedback == "unhelpful" and intent.source != "current_turn":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("negative_feedback")
    elif intent.advice_preference == "declined":
        primary, secondary = "supportive_listening", "reflect_feelings"
        reasons.append("advice_declined")
    elif intent.primary == "venting":
        primary, secondary = "supportive_listening", "reflect_feelings"
        reasons.append("listen_requested")
    elif (
        intent.primary == "seeking_practical_help"
        and intent.advice_preference == "requested"
    ):
        primary, secondary = "collaborative_problem_solving", "offer_small_step"
        reasons.append("advice_requested")
    elif intent.primary == "seeking_clarification":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("clarification_requested")
    elif intent.feedback == "unhelpful":
        primary, secondary = "reflect_and_clarify", "explore_context"
        reasons.append("negative_feedback")
    elif (
        context.protocol_control_detected
        or protocol_boundary(context.user_text).detected
    ):
        primary = (
            "validate_and_ground"
            if context.current_state.risk_level == RiskLevel.ELEVATED
            or max(context.current_state.emotion.model_dump().values()) >= 0.7
            else "supportive_listening"
        )
        secondary = "explore_context"
        reasons.append("protocol_control_ignored")
    if primary:
        result.strategy = StrategyDecision(
            primary=primary, secondary=secondary, avoid=list(proposed.strategy.avoid)
        )
    result.trace.coordination = CoordinationTrace(
        proposed_strategy=proposed.strategy.primary,
        final_strategy=result.strategy.primary,
        previous_strategy=context.previous_strategy,
        reason_codes=reasons,
    )
    return result
