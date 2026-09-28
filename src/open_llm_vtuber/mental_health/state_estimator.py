"""Simple non-clinical psychological state estimation baseline."""

import re
from typing import ClassVar

from .schemas import PsychologicalState, RiskLevel, SafetyCheckResult


class KeywordStateEstimator:
    _EMOTION_TERMS: ClassVar[dict[str, tuple[str, ...]]] = {
        "stress": (
            "压力",
            "累",
            "疲惫",
            "工作太多",
            "stress",
            "overwhelmed",
            "exhausted",
        ),
        "anxiety": (
            "焦虑",
            "紧张",
            "害怕",
            "担心",
            "恐慌",
            "anxious",
            "worried",
            "panic",
        ),
        "low_mood": (
            "难过",
            "低落",
            "绝望",
            "没意思",
            "孤独",
            "sad",
            "hopeless",
            "lonely",
        ),
    }
    _TOPIC_TERMS: ClassVar[dict[str, tuple[str, ...]]] = {
        "work": ("工作", "上班", "同事", "老板", "work", "job", "coworker"),
        "study": ("学习", "考试", "作业", "学校", "study", "exam", "school"),
        "family": ("家人", "父母", "家庭", "孩子", "family", "parent"),
        "relationship": ("恋爱", "分手", "伴侣", "朋友", "relationship", "breakup"),
        "sleep": ("失眠", "睡不着", "睡眠", "insomnia", "sleep"),
        "health": ("生病", "身体", "疼痛", "健康", "ill", "pain", "health"),
    }

    async def estimate(
        self, text: str, safety: SafetyCheckResult
    ) -> PsychologicalState:
        normalized = text.lower()
        scores = {
            name: self._score(normalized, terms)
            for name, terms in self._EMOTION_TERMS.items()
        }
        topics = [
            name
            for name, terms in self._TOPIC_TERMS.items()
            if any(self._contains(normalized, term) for term in terms)
        ]
        strategy = self._strategy(safety.risk_level, scores)
        labels = [name for name, score in scores.items() if score >= 0.35]
        summary_parts = []
        if labels:
            summary_parts.append("estimated signals: " + ", ".join(labels))
        if topics:
            summary_parts.append("topics: " + ", ".join(topics))
        if not summary_parts:
            summary_parts.append("no strong psychological state signal estimated")

        return PsychologicalState(
            schema_version=2,
            estimator_source="keyword_v1",
            confidence="low" if labels else "unknown",
            observed_dimensions=labels,
            emotion=scores,
            topics=topics,
            interaction_strategy=strategy,
            risk_level=safety.risk_level,
            risk_signals=safety.signals,
            summary="; ".join(summary_parts),
        )

    @staticmethod
    def _score(text: str, terms: tuple[str, ...]) -> float:
        matches = sum(
            1 for term in terms if KeywordStateEstimator._contains(text, term)
        )
        return min(1.0, matches * 0.35)

    @staticmethod
    def _contains(text: str, term: str) -> bool:
        if term.isascii():
            return re.search(rf"\b{re.escape(term)}\b", text) is not None
        return term in text

    @staticmethod
    def _strategy(risk_level: RiskLevel, scores: dict[str, float]) -> str:
        if risk_level == RiskLevel.CRITICAL:
            return "crisis_support"
        if risk_level == RiskLevel.HIGH:
            return "safety_check_in"
        if risk_level == RiskLevel.ELEVATED or max(scores.values(), default=0.0) >= 0.7:
            return "validation_and_grounding"
        return "supportive_listening"
