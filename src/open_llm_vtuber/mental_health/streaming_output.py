"""Frame model deltas into complete units for the local output safety gate."""

from collections.abc import AsyncIterator, Iterable
import re


def delta_text(event) -> str:
    if isinstance(event, str):
        return event
    if isinstance(event, dict) and event.get("type") == "text_delta":
        text = event.get("text")
        if isinstance(text, str):
            return text
    return ""


async def safety_units(
    events: AsyncIterator, expressions: Iterable[str]
) -> AsyncIterator[str]:
    # The divider used for display can split on a comma. Safety needs the full
    # sentence first. Bound unpunctuated speech without cutting a control tag.
    limit = 60
    markers = [f"[{name.lower()}]" for name in expressions] + [
        "<think>",
        "</think>",
        "<think/>",
    ]
    pending = ""
    has_text = False
    async for event in events:
        pending += delta_text(event)
        while pending:
            prefix = pending[:limit]
            end = re.search(r"[。！？!?\n]|(?<!\d)\.", prefix)
            if end:
                cut = end.end()
            elif len(pending) >= limit:
                cut = limit
                partial = re.search(r"(\[[^\[\]]*|<[^<>]*)$", prefix)
                if (
                    partial
                    and partial.start()
                    and any(
                        mark.startswith(partial.group().lower()) for mark in markers
                    )
                ):
                    cut = partial.start()
            else:
                break
            part, pending = pending[:cut], pending[cut:]
            if part.strip():
                has_text = True
                yield part
    if pending.strip() or not has_text:
        yield pending
