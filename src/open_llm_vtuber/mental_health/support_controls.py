"""Explicit UI choices augment the existing text intent estimator."""

MODES = {
    "listen": ("venting", "declined"),
    "clarify": ("seeking_clarification", "unspecified"),
    "solve": ("seeking_practical_help", "requested"),
}


def resolve_support_intent(intent, mode, feedback="unspecified"):
    intent = intent.model_copy(deep=True)
    natural = {
        "venting": "listen",
        "seeking_clarification": "clarify",
        "seeking_practical_help": "solve",
        "ending": None,
    }
    if intent.certainty == "explicit" and intent.primary in natural:
        mode = natural[intent.primary]
    elif mode in MODES:
        intent.primary, intent.advice_preference = MODES[mode]
        intent.certainty = "explicit"
        intent.source = "user_control"
        intent.preference_source = "recent_turn"
    if feedback != "unspecified" and intent.feedback == "unspecified":
        intent.feedback = feedback
        intent.feedback_source = "user_control"
    return intent, mode
