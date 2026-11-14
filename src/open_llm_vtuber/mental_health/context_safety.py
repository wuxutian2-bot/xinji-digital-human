"""Opt-in contextual guard; retains the frozen v1 implementation for comparison."""

import re

from .context_signals import context_clauses, explicitly_resolved
from .crisis_resources import CRISIS_CONTACT_TEXT
from .safety_guard import RuleBasedSafetyGuard
from .schemas import ContextEvidence, RiskLevel, SafetyAction, SafetyCheckResult


class ContextSafetyGuard(RuleBasedSafetyGuard):
    _MEDICATION = "请不要服用开给别人的处方药，也不要自行决定剂量。请先让医生或药师帮你核实适合你的处理方式。如果已经误服或服用了过量药物，请立即联系当地急救服务。"
    _CONNECTION = "你希望有人认真听你说，我愿意听。也请给现实中的支持留一个位置。有没有一位你信任、愿意保持联系的人？"
    _REPORTED = re.compile(
        r"(?:朋友|室友|同学|家人|妹妹|弟弟)(?:刚刚?|发消息|跟我|和我|告诉我|跟我发消息|给我发消息|今晚|现在|表示|发来消息|来信|\s|说|称|他|她|[:：“]){0,8}(?:想自杀|想要自杀|不想活|想伤害自己|要自杀)"
    )

    async def check_input(self, text):
        return await self.check_input_with_context(text, None)

    async def check_input_with_context(self, text, previous=None):
        clauses = context_clauses(text)
        evidence = [c.evidence.model_copy(deep=True) for c in clauses]
        checks = []
        crisis_clauses = []
        for clause, metadata in zip(clauses, evidence):
            if clause.harm_mentioned and clause.exempt_harm:
                continue
            check = await super().check_input(clause.text)
            # Unattributed or third-person real harm is retained, not cleared by quotes.
            if (
                clause.harm_mentioned
                and not clause.exempt_harm
                and check.action != SafetyAction.ESCALATE
            ):
                check = SafetyCheckResult(
                    action=SafetyAction.ESCALATE,
                    risk_level=RiskLevel.HIGH,
                    signals=["context_harm_language"],
                )
            if check.action == SafetyAction.ESCALATE:
                metadata.evidence_codes.append("risk_retained")
                crisis_clauses.append(clause.text)
            checks.append(check)
        retained_prior = previous is not None and (
            previous.action == SafetyAction.ESCALATE
            or (
                (
                    "context_harm_mentioned" in previous.signals
                    or any(
                        "harm_mentioned" in e.evidence_codes
                        for e in previous.context_evidence
                    )
                )
                and re.search(
                    r"这是我现在|我现在的想法|其实.{0,8}我|that is how i feel|those are my thoughts",
                    text,
                    re.I,
                )
            )
        )
        if retained_prior and not explicitly_resolved(text):
            checks.append(
                SafetyCheckResult(
                    action=SafetyAction.ESCALATE,
                    risk_level=RiskLevel.HIGH,
                    signals=["prior_risk_unresolved"],
                )
            )
            evidence.insert(
                0,
                ContextEvidence(
                    clause_index=0,
                    evidence_codes=["prior_risk_continues"],
                    uncertainty=True,
                ),
            )
        order = {
            RiskLevel.LOW: 0,
            RiskLevel.ELEVATED: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }
        result = (
            max(checks, key=lambda c: order[c.risk_level])
            if checks
            else SafetyCheckResult(action=SafetyAction.ALLOW)
        )
        if result.action == SafetyAction.ESCALATE:
            result.safe_response = self._localized_response(
                text, self._CRISIS_RESPONSE, self._CRISIS_RESPONSE_EN
            )
            if (
                crisis_clauses
                and all(self._REPORTED.search(c) for c in crisis_clauses)
                and not retained_prior
                and not re.search(
                    r"我(?:也|自己|现在|正|已经)*(?:想|准备|打算)(?:自杀|伤害自己|去死)",
                    text,
                )
            ):
                result.safe_response = (
                    "你能联系上对方吗？先问问对方在哪里、现在是否安全、是否已经采取行动。"
                    "如果有眼前的危险、已经受伤或此时联系不上，请立即联系对方所在地的急救服务，并通知能赶到对方身边的人。"
                    "可以的话，保持通话，陪对方等到有人接手。" + CRISIS_CONTACT_TEXT
                )
                result.signals.append("reported_person_at_risk")
        elif re.search(
            r"(?:家人|朋友|别人|室友|我妈|我爸)(?:的|剩下的|吃的)(?:处方药|安眠药|药)",
            text,
        ) and re.search(r"我.{0,12}(?:吃|服|用)|吃多少|剂量|能吃吗", text):
            result.safe_response = self._MEDICATION
            result.action = SafetyAction.SUPPORT
            result.signals.append("prescription_boundary")
        elif re.search(
            r"只(?:想|要)?(?:找你|跟你|和你|靠你|需要你)", text
        ) and re.search(
            r"不(?:再)?(?:跟|和|找|联系)|断(?:绝|开)联系|不理(?:别人|朋友)", text
        ):
            result.safe_response = self._CONNECTION
            result.action = SafetyAction.SUPPORT
            result.signals.append("real_world_support")
        result.context_version = 2
        if any(c.harm_mentioned for c in clauses):
            result.signals = [*result.signals, "context_harm_mentioned"]
        result.context_evidence = evidence[:64]  # Cap persistence, never risk scanning.
        return result

    async def check_output(self, text):
        if not text.strip():
            return await super().check_output(text)
        # Remove only complete non-harm instructions from the unsafe-advice scan.
        remaining = []
        for clause in re.split(r"[。！？.!?\n]", text):
            if re.fullmatch(
                r"\s*(?:你(?:应该|可以)?(?:不要|不应该|不能)(?:去)?(?:自杀|伤害自己|伤害他人)|you (?:should not|must not|should never|must never|do not) (?:hurt yourself|kill yourself|hurt someone))\s*",
                clause,
                re.I,
            ):
                continue
            remaining.append(clause)
        result = (
            await super().check_output("。".join(remaining))
            if any(c.strip() for c in remaining)
            else SafetyCheckResult(action=SafetyAction.ALLOW)
        )
        if result.action == SafetyAction.ALLOW:
            for pattern, reply in (
                (
                    r"(?:^|[，。！？\s])(?:以后|那你|你)?只(?:要|需要)?(?:找我|跟我聊|和我说话|依靠我)(?:就好|就够|就行)|不用(?:再)?(?:联系|找)(?:朋友|家人|其他人)",
                    self._CONNECTION,
                ),
                (
                    r"(?:你可以|建议你|你应该|不妨|试试|先)(?:先)?(?:服用|吃|服)(?:上|下)?(?:半|[一二两三四五六七八九十\d.]+)(?:毫克|mg|(?:片|粒)(?:药|处方药|安眠药|镇静剂|[。！？!?，,]|$))",
                    self._MEDICATION,
                ),
            ):
                if re.search(pattern, text, re.I):
                    return SafetyCheckResult(
                        action=SafetyAction.BLOCK,
                        safe_response=reply,
                        reason="Unsafe generated guidance.",
                    )
            if re.search(
                r"我诊断你有(?:抑郁症|焦虑症)|\bi diagnose you with (?:depression|anxiety)",
                text,
                re.I,
            ):
                return SafetyCheckResult(
                    action=SafetyAction.REWRITE,
                    reason="Unsupported diagnostic assertion.",
                    safe_response="仅凭对话无法作出诊断。你描述的感受值得被认真关注，可以寻求合格专业人员的评估。",
                )
            result.safe_response = text
        return result
