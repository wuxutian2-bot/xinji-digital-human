"""Small, conservative intent baseline. Safety always examines the original text."""

import re

from .schemas import InteractionIntent
from .context_signals import protocol_boundary


class IntentEstimator:
    _QUOTE = re.compile(r'“[^”]*”|「[^」]*」|"[^"\n]*"|```[\s\S]*?```')
    _CONTROL = re.compile(
        r"忽略.{0,12}规则|输出\s*json|把.{0,8}(策略|primary).{0,8}(设|写)|\b(ignore.{0,12}rules|set\s+primary)\b",
        re.I,
    )
    # Match whole clauses, avoiding incidental mentions and third-party quotations.
    _RULES = (
        (
            "declined",
            "venting",
            "explicit_no_advice",
            r"(?:我)?(?:现在|暂时|先)?(?:别|不要|不想要)(?:给我|给|任何|你的)?建议(?:了)?|(?:please\s+)?(?:don't|do not) give me advice",
        ),
        (
            "declined",
            "venting",
            "explicit_listen_request",
            r"(?:我)?(?:只是|只)?想(?:倾诉|吐槽|让你听我说)(?:一下)?|(?:请)?(?:只要|就)?听我说(?:说)?|just listen(?: please)?",
        ),
        (
            "requested",
            "seeking_practical_help",
            "explicit_advice_request",
            r"(?:我)?(?:现在)?可以给(?:我)?建议了|(?:请|能|可以)?(?:给我|给)(?:一[个些点]|一些|点|些)?(?:办法|建议|小步骤)(?:吗|吧)?|(?:能|可以)?帮我想.{0,20}(?:办法|步骤|建议)(?:吗)?|please give me (?:some )?advice",
        ),
        (
            None,
            "ending",
            "explicit_closure",
            r"(?:我们)?(?:今天|现在)?(?:先|就)?(?:聊到这里|聊到这|不聊了|结束聊天)(?:吧|了)?|(?:先)?再见|(?:let's )?(?:stop here|end the conversation)|goodbye",
        ),
        (
            None,
            "seeking_clarification",
            "explicit_clarification_request",
            r"(?:我想|请帮我|帮我)(?:先)?(?:理清|梳理).{0,20}|help me (?:understand|clarify).{0,40}",
        ),
        (
            None,
            "seeking_information",
            "information_question",
            r"[^。！？!?]{1,24}(?:是什么|是什么意思)|what (?:is|does) .{1,50}",
        ),
        (None, "small_talk", "greeting", r"你好(?:呀|啊)?|您好|hello|hi"),
    )
    _FEEDBACK = (
        (
            "unhelpful",
            r"(?:这个|刚才的)?(?:建议|回答)(?:没帮助|没有帮助|没用)|that (?:was not|wasn't) helpful",
        ),
        (
            "helpful",
            r"(?:这个|刚才的)?(?:建议|回答)(?:很有帮助|有帮助)|that was helpful",
        ),
    )

    def estimate(
        self, text: str, previous: InteractionIntent | None = None
    ) -> InteractionIntent:
        result = InteractionIntent()
        if previous and previous.advice_preference != "unspecified":
            result.advice_preference = previous.advice_preference
            result.preference_source = "recent_turn"
            result.evidence_codes.append("carried_preference")
        # Removing quotes is only an intent heuristic, never a Safety exemption.
        cleaned = self._QUOTE.sub(" ", protocol_boundary(text).model_text).strip()
        for clause in re.split(r"[，。！？；,;!?\n]+", cleaned):
            clause = clause.strip().rstrip(".")
            if not clause or self._CONTROL.search(clause):
                continue
            for preference, primary, evidence, pattern in self._RULES:
                if re.fullmatch(pattern, clause, re.I):
                    result.primary = primary
                    result.certainty = (
                        "inferred" if primary == "seeking_information" else "explicit"
                    )
                    result.source = "current_turn"
                    if preference:
                        result.advice_preference = preference
                        result.preference_source = "current_turn"
                    if evidence not in result.evidence_codes:
                        result.evidence_codes.append(evidence)
                    break
            for feedback, pattern in self._FEEDBACK:
                if re.fullmatch(pattern, clause, re.I):
                    result.feedback = feedback
                    result.feedback_source = "current_turn"
                    code = "feedback_" + feedback
                    if code not in result.evidence_codes:
                        result.evidence_codes.append(code)
        return result


def format_intent_context(
    intent: InteractionIntent, previous_strategy: str | None
) -> str:
    return (
        "Locally estimated interaction intent (unknown is not consent): "
        + intent.model_dump_json()
        + f"\nPrevious completed strategy: {previous_strategy or 'unknown'}. "
        "Respect a declined advice preference: listen and reflect without unsolicited steps. "
        "When ending, close briefly without another question. Explicit risk still takes precedence. "
        "Helpful/unhelpful refers only to explicit user feedback; silence or interruption is not feedback."
    )
