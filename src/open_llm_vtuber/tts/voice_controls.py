"""Resolve per-utterance controls without mutating a shared TTS engine."""

from math import isfinite


def resolve_voice_controls(engine, actions) -> dict:
    supported = getattr(engine, "supported_controls", frozenset())
    requested = getattr(actions, "voice_speed", None)
    valid_speed = (
        isinstance(requested, (int, float))
        and not isinstance(requested, bool)
        and isfinite(requested)
        and 0.6 <= requested <= 1.5
    )
    speed = float(requested) if valid_speed and "speed" in supported else 1.0
    fallback = []
    if requested is not None and (not valid_speed or "speed" not in supported):
        fallback.append("speed")
    for field in ("style", "energy"):
        if getattr(actions, f"voice_{field}", None) is not None:
            fallback.append(field)
    return {"speed": speed, "fallback": fallback}
