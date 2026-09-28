"""Opt-in contextual guard; retains the frozen v1 implementation for comparison."""

import re

from .context_signals import context_clauses, explicitly_resolved
from .safety_guard import RuleBasedSafetyGuard
from .schemas import ContextEvidence, RiskLevel, SafetyAction, SafetyCheckResult


class ContextSafetyGuard(RuleBasedSafetyGuard):
    async def check_input(self, text):
        return await self.check_input_with_context(text, None)

    async def check_input_with_context(self, text, previous=None):
        clauses = context_clauses(text)
        evidence = [c.evidence.model_copy(deep=True) for c in clauses]
        checks = []
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
