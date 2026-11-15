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
    result = {"speed": speed, "style": None, "energy": None, "fallback": fallback}
    style = getattr(actions, "voice_style", None)
    if (
        isinstance(style, str)
        and style in {"calm", "warm", "steady"}
        and "style" in supported
    ):
        result["style"] = style
    elif style is not None:
        fallback.append("style")
    energy = getattr(actions, "voice_energy", None)
    valid_energy = (
        isinstance(energy, (int, float))
        and not isinstance(energy, bool)
        and isfinite(energy)
        and 0.5 <= energy <= 1.5
    )
    if valid_energy and "energy" in supported:
        result["energy"] = float(energy)
    elif energy is not None:
        fallback.append("energy")
    for field, attribute in (
        ("voice_id", "voice_id"),
        ("instruction", "voice_instruction"),
    ):
        value = getattr(actions, attribute, None)
        if isinstance(value, str) and value.strip() and field in supported:
            result[field] = value
        elif value is not None:
            fallback.append(field)
    return result
