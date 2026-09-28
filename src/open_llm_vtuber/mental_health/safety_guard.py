"""Mandatory deterministic safety gates for phase 2."""

import re
from typing import ClassVar

from .schemas import RiskLevel, SafetyAction, SafetyCheckResult


class RuleBasedSafetyGuard:
    """Conservative local baseline that does not depend on an LLM decision."""

    _CRITICAL_INPUT_PATTERNS = (
        re.compile(
            r"(我|自己).{0,8}(想|要|准备|打算).{0,5}(死|自杀|结束生命|伤害自己)"
        ),
        re.compile(r"(不想活了|活不下去了|结束我的生命|马上去死)"),
        re.compile(r"(我|自己).{0,8}(想|要|准备|打算).{0,5}(杀人|伤害别人|伤害他人)"),
        re.compile(
            r"\b(i want to|i am going to|i'm going to|i plan to).{0,20}"
            r"(die|kill myself|end my life|hurt someone|kill someone)\b",
            re.IGNORECASE,
        ),
    )
    _HIGH_INPUT_PATTERNS = (
        re.compile(r"(割腕|跳楼|服药自杀|伤害自己|自残)"),
        re.compile(r"\b(self[- ]?harm|suicidal|hurt myself)\b", re.IGNORECASE),
    )
    _ELEVATED_INPUT_PATTERNS = (
        re.compile(r"(绝望|崩溃|撑不下去|没人关心我|没有希望)"),
        re.compile(
            r"\b(hopeless|cannot go on|can't go on|nobody cares)\b", re.IGNORECASE
        ),
    )
    _DANGEROUS_OUTPUT_PATTERNS = (
        re.compile(r"(你应该|那就|你可以).{0,8}(自杀|去死|伤害自己|伤害他人)"),
        re.compile(
            r"\b(you should|go ahead and).{0,15}"
            r"(kill yourself|hurt yourself|hurt someone)\b",
            re.IGNORECASE,
        ),
    )
    _DIAGNOSIS_REWRITES: ClassVar[dict[str, str]] = {
        "你患有抑郁症": "你描述的持续低落值得被认真关注，但仅凭对话无法作出诊断",
        "你就是抑郁症": "这些感受可能与持续低落有关，但仅凭对话无法作出诊断",
        "你患有焦虑症": "你描述的焦虑感值得被认真关注，但仅凭对话无法作出诊断",
        "you have depression": "your low mood deserves attention, but this conversation cannot diagnose you",
        "you have an anxiety disorder": "your anxiety deserves attention, but this conversation cannot diagnose you",
    }

    _CRISIS_RESPONSE = (
        "我很重视你刚才说的内容。你现在是否正准备伤害自己或他人，或者已经采取了行动？"
        "如果是，请立即联系当地急救服务或危机热线，并尽快让一位可信任的人来到你身边；"
        "同时远离可能造成伤害的物品，前往有人陪伴的安全地点。请告诉我：你现在安全吗？"
    )
    _CRISIS_RESPONSE_EN = (
        "I am taking what you said seriously. Are you about to hurt yourself or "
        "someone else, or have you already taken action? If so, contact local "
        "emergency services or a crisis line now, ask a trusted person to stay "
        "with you, move away from anything that could cause harm, and go to a "
        "safer place with other people. Please tell me: are you safe right now?"
    )
    _BLOCKED_OUTPUT_RESPONSE = (
        "我不能提供或强化可能造成伤害的建议。你的安全更重要。"
        "如果你现在有立即伤害自己或他人的危险，请马上联系当地急救服务、危机热线，"
        "或请一位可信任的人陪在你身边。"
    )
    _BLOCKED_OUTPUT_RESPONSE_EN = (
        "I cannot provide or reinforce advice that could cause harm. Your safety "
        "matters more. If you are in immediate danger of hurting yourself or "
        "someone else, contact local emergency services or a crisis line now, "
        "or ask a trusted person to stay with you."
    )
    _EMPTY_OUTPUT_RESPONSE = (
        "我暂时没能生成合适的回应。你愿意再告诉我一些现在的感受吗？"
    )

    async def check_input(self, text: str) -> SafetyCheckResult:
        normalized = text.strip()
        if self._matches(normalized, self._CRITICAL_INPUT_PATTERNS):
            return SafetyCheckResult(
                action=SafetyAction.ESCALATE,
                risk_level=RiskLevel.CRITICAL,
                signals=["immediate_harm_language"],
                reason="Input contains an immediate harm risk signal.",
                safe_response=self._localized_response(
                    normalized, self._CRISIS_RESPONSE, self._CRISIS_RESPONSE_EN
                ),
            )
        if self._matches(normalized, self._HIGH_INPUT_PATTERNS):
            return SafetyCheckResult(
                action=SafetyAction.ESCALATE,
                risk_level=RiskLevel.HIGH,
                signals=["self_or_other_harm_language"],
                reason="Input contains a high-risk harm signal.",
                safe_response=self._localized_response(
                    normalized, self._CRISIS_RESPONSE, self._CRISIS_RESPONSE_EN
                ),
            )
        if self._matches(normalized, self._ELEVATED_INPUT_PATTERNS):
            return SafetyCheckResult(
                action=SafetyAction.SUPPORT,
                risk_level=RiskLevel.ELEVATED,
                signals=["distress_language"],
                reason="Input contains an elevated distress signal.",
            )
        return SafetyCheckResult(action=SafetyAction.ALLOW)

    async def check_output(self, text: str) -> SafetyCheckResult:
        if not text.strip():
            return SafetyCheckResult(
                action=SafetyAction.REWRITE,
                reason="The generated response was empty.",
                safe_response=self._EMPTY_OUTPUT_RESPONSE,
            )
        if self._matches(text, self._DANGEROUS_OUTPUT_PATTERNS):
            return SafetyCheckResult(
                action=SafetyAction.BLOCK,
                risk_level=RiskLevel.HIGH,
                signals=["unsafe_generated_advice"],
                reason="The generated response encouraged harmful action.",
                safe_response=self._localized_response(
                    text,
                    self._BLOCKED_OUTPUT_RESPONSE,
                    self._BLOCKED_OUTPUT_RESPONSE_EN,
                ),
            )

        rewritten = text
        for unsafe_phrase, safe_phrase in self._DIAGNOSIS_REWRITES.items():
            rewritten = re.sub(
                re.escape(unsafe_phrase),
                safe_phrase,
                rewritten,
                flags=re.IGNORECASE,
            )
        if rewritten != text:
            return SafetyCheckResult(
                action=SafetyAction.REWRITE,
                reason="Replaced unsupported diagnostic language.",
                safe_response=rewritten,
            )
        return SafetyCheckResult(
            action=SafetyAction.ALLOW,
            safe_response=text,
        )

    @staticmethod
    def _matches(text: str, patterns: tuple[re.Pattern, ...]) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @staticmethod
    def _localized_response(text: str, chinese: str, english: str) -> str:
        return chinese if re.search(r"[\u4e00-\u9fff]", text) else english
