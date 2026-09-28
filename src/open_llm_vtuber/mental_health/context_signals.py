"""Local protocol boundary; this module never grants a Safety exemption.

Context interpretation is conservative and keeps uncertain harm mentions visible.
"""

from copy import deepcopy
from dataclasses import dataclass
import re

from .schemas import ContextEvidence


_QUOTES = re.compile(r'“[^”]*”|「[^」]*」|"[^"\n]*"|```[\s\S]*?```')
_CLAUSES = re.compile(r"[^，。！？；,;!?.\n]+[，。！？；,;!?.\n]*")
_CONTROL = re.compile(
    r"^(?:请|请你|现在|please\s+)?(?:"
    r"忽略.{0,16}(?:规则|指令|安全|提示)|"
    r"(?:把|将).{0,8}(?:策略|primary|secondary|behavior|voice).{0,8}(?:设|写|改)|"
    r"(?:设置|修改|覆盖)(?:内部)?(?:策略|primary|secondary|系统提示|安全规则)|"
    r"(?:输出|返回|生成)\s*json|"
    r"(?:ignore|override)\b.{0,24}\b(?:rules|instructions|safety|system)|"
    r"(?:set|change|write)\s+(?:the\s+)?(?:primary|secondary|strategy|behavior|voice)\b|"
    r"(?:return|output|generate)\s+(?:only\s+)?json\b)",
    re.I,
)
_CONTINUATION = re.compile(r"^(?:添加额外字段|add (?:an? )?extra field)", re.I)
_PLACEHOLDER = "用户请求尚未提供可识别的支持话题。"


@dataclass(frozen=True)
class ProtocolBoundary:
    detected: bool
    control_only: bool
    model_text: str


def protocol_boundary(text: str) -> ProtocolBoundary:
    """Drop recognized command clauses from model input, keeping original Safety input."""
    # Preserve offsets so quoted examples do not become imperative commands.
    masked = _QUOTES.sub(lambda match: " " * len(match.group()), text)
    detected = False
    kept = []
    for part in _CLAUSES.finditer(text):
        candidate = masked[part.start() : part.end()].strip()
        # Clipboard wrappers denote untrusted user-provided text too.
        candidate = re.sub(r"^\[User shared content from clipboard:\s*", "", candidate)
        if _CONTROL.search(candidate) or (detected and _CONTINUATION.search(candidate)):
            detected = True
        else:
            kept.append(part.group())
    if not detected:
        return ProtocolBoundary(False, False, text)
    remaining = "".join(kept).strip()
    meaningful = remaining.strip("，。！？；,;!?.\n []")
    return ProtocolBoundary(
        True, not meaningful, remaining if meaningful else _PLACEHOLDER
    )


def sanitize_model_messages(messages):
    """Copy text blocks, including loaded history; never mutate chat records or images."""
    result = deepcopy(messages)
    for message in result:
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = protocol_boundary(content).model_text
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    block["text"] = protocol_boundary(block["text"]).model_text
    return result


def protocol_redirect(text, advice_declined=False):
    if advice_declined:
        return (
            "我在这里，会先听你说。你愿意说说现在的感受吗？"
            if re.search(r"[\u4e00-\u9fff]", text)
            else "I am here to listen. Would you like to share how you feel right now?"
        )
    if re.search(r"[\u4e00-\u9fff]", text):
        return "我在这里。你希望我听你说说，还是一起想一个具体办法？"
    return "I am here. Would you like me to listen, or help you think through a small next step?"


HARM = re.compile(
    r"自杀|自残|伤害自己|伤害他人|伤害别人|结束生命|不想活|割腕|跳楼|杀人|\b(?:suicidal|suicide|self[- ]harm\w*|hurt\s+(?:myself|yourself|someone)|kill\s+(?:myself|yourself|someone)|end\s+my\s+life|die)\b",
    re.I,
)
_FICTION = re.compile(
    r"小说里|小说中|电影中|虚构故事|故事角色|电影里的|小说角色|\b(?:novel|fictional|film|movie|narrator)\b",
    re.I,
)
_OTHER = re.compile(
    r"朋友|他|她|家人|同学|孩子|\b(?:friend|he|she|they|someone|parent)\b", re.I
)
_SELF = re.compile(r"我(?!们)|自己|\b(?:i|myself|my)\b", re.I)
_PAST = re.compile(r"以前|去年|年前|曾经|过去|\b(?:used to|years ago|was|were)\b", re.I)
_CURRENT = re.compile(
    r"现在|正在|此刻|今天|马上|\b(?:now|today|tonight|currently)\b", re.I
)
_DOUBLE = re.compile(
    r"不是不|并非没有|不能说.{0,8}不|\b(?:cannot say|can.t say|not.*not)\b", re.I
)
_DENIAL = re.compile(
    r"^(?:我)?(?:现在|今天|目前)?(?:并)?(?:不想|不会|没有|不|没|并不)(?:再|任何|要)?(?:自杀|自残|伤害自己|伤害他人|伤害别人|焦虑|难过|紧张|害怕|低落|孤独|压力|疲惫)|^i\s+(?:am not|do not|don.t|will not|won.t|have no)\s+(?:want to\s+)?(?:hurt myself|kill myself|suicidal|anxious|sad|worried|lonely|stressed)",
    re.I,
)
_HARM_DENIAL_WHOLE = re.compile(
    r"(?:我)?(?:现在|今天|目前)?(?:并)?(?:不想|不会|没有)(?:再|任何|要)?(?:自杀|自残|伤害自己|伤害他人|伤害别人)(?:的(?:想法|念头))?(?:了)?|i\s+(?:am not|do not|don.t|will not|won.t)\s+(?:want to\s+)?(?:hurt myself|kill myself|suicidal)",
    re.I,
)
_RESOLVED = re.compile(
    r"(?:现在|如今|目前).{0,12}(?:没有这些想法|没有伤害自己的念头|没有自杀的想法)|\bi am safe now with no such thoughts\b",
    re.I,
)
_SAFETY_CONFIRMATION = re.compile(r"安全|有人陪|\bsafe\b", re.I)


@dataclass(frozen=True)
class ContextClause:
    text: str  # Ephemeral only. Persist metadata through evidence, never this text.
    evidence: ContextEvidence
    harm_mentioned: bool
    exempt_harm: bool


def explicitly_resolved(text):
    return bool(_RESOLVED.search(text) and _SAFETY_CONFIRMATION.search(text))


def context_clauses(text):
    """Segment outside quotes; an unclosed quote stays uncertain and cannot exempt risk."""
    pieces, current, closing = [], [], None
    quote_pairs = {"“": "”", "「": "」", '"': '"'}
    for char in text:
        if closing:
            if char == closing:
                closing = None
        elif char in quote_pairs:
            closing = quote_pairs[char]
        if not closing and char in "，。！？；,;!?.\n":
            if current:
                pieces.append(("".join(current).strip(), char in "。！？;；!?.\n"))
                current = []
        else:
            current.append(char)
    if current:
        pieces.append(("".join(current).strip(), True))
    inherited = "unknown"
    resolved = explicitly_resolved(text)
    clauses = []
    for index, (raw, sentence_end) in enumerate(pieces):
        raw = re.sub(
            r"^(?:但是|但|而|可是|不过|but\s+|however\s+)", "", raw, flags=re.I
        ).strip()
        outside = _QUOTES.sub(" ", raw).strip()
        quoted = outside != raw
        fiction = bool(_FICTION.search(outside)) and not re.search(
            r"不是|非虚构|not (?:a )?(?:movie|novel|fiction)", outside, re.I
        )
        if re.search(
            r"我现在|我正在|我准备|我打算|i (?:am going|plan|want)", outside, re.I
        ):
            fiction = False
        if re.search(
            r"我想.{0,8}(?:自杀|结束生命|伤害自己|伤害他人)", outside
        ) and not re.search(
            r"(?:故事|小说).{0,12}(?:写着|写道|角色说)\s*[:：]", outside
        ):
            fiction = False
        # A real-person assertion after a fictional introduction starts its own clause.
        if fiction:
            subject = "fiction"
        elif _OTHER.search(outside):
            subject = "other"
        elif _SELF.search(outside):
            subject = "self"
        else:
            subject = inherited
        temporal = (
            "past"
            if _PAST.search(outside)
            else "current"
            if _CURRENT.search(outside) or subject == "self"
            else "unknown"
        )
        double = bool(_DOUBLE.search(outside))
        negated = bool(_DENIAL.search(outside)) and not double
        assertion = "negated" if negated else "quoted" if quoted else "affirmed"
        if subject == "unknown" or double or closing:
            assertion = "uncertain"
        codes = []
        if subject in ("self", "other"):
            codes.append("explicit_" + subject)
        if subject == "fiction":
            codes.append("fiction_context")
        if temporal in ("past", "current"):
            codes.append(temporal + "_marker")
        if negated:
            codes.append("explicit_denial")
        if quoted:
            codes.append("quotation")
        harm = bool(HARM.search(raw))
        if harm:
            codes.append("harm_mentioned")
        # Exempt only a whole direct denial, explicit fiction, or resolved past event.
        deny_whole = negated and bool(_HARM_DENIAL_WHOLE.fullmatch(outside.strip()))
        exempt = (
            not closing
            and not double
            and (
                subject == "fiction" or deny_whole or (temporal == "past" and resolved)
            )
        )
        uncertain = assertion == "uncertain" or temporal == "unknown"
        if uncertain:
            codes.append("ambiguous_scope")
        clauses.append(
            ContextClause(
                raw,
                ContextEvidence(
                    clause_index=index,
                    subject=subject,
                    temporality=temporal,
                    assertion=assertion,
                    uncertainty=uncertain,
                    evidence_codes=codes,
                ),
                harm,
                exempt,
            )
        )
        inherited = "unknown" if sentence_end else subject
    return clauses
