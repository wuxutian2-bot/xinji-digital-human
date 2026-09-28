"""Typed, non-diagnostic schemas for the mental health cognitive layer."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class RiskLevel(str, Enum):
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyAction(str, Enum):
    ALLOW = "allow"
    SUPPORT = "support"
    ESCALATE = "escalate"
    REWRITE = "rewrite"
    BLOCK = "block"


class ContextEvidence(BaseModel):
    """Non-diagnostic clause metadata; no source text persisted."""

    model_config = ConfigDict(extra="forbid")
    clause_index: int = Field(ge=0)
    subject: Literal["self", "other", "fiction", "unknown"] = "unknown"
    temporality: Literal["current", "past", "unknown"] = "unknown"
    assertion: Literal["affirmed", "negated", "quoted", "uncertain"] = "uncertain"
    uncertainty: bool = True
    evidence_codes: list[
        Literal[
            "explicit_self",
            "explicit_other",
            "fiction_context",
            "past_marker",
            "current_marker",
            "explicit_denial",
            "quotation",
            "ambiguous_scope",
            "harm_mentioned",
            "risk_retained",
            "prior_risk_continues",
        ]
    ] = Field(default_factory=list, max_length=12)


class SafetyCheckResult(BaseModel):
    action: SafetyAction
    risk_level: RiskLevel = RiskLevel.LOW
    signals: list[str] = Field(default_factory=list)
    reason: str = ""
    safe_response: str | None = None
    context_version: Literal[2] | None = None
    context_evidence: list[ContextEvidence] = Field(default_factory=list, max_length=64)


class EmotionEstimate(BaseModel):
    stress: float = Field(0.0, ge=0.0, le=1.0)
    anxiety: float = Field(0.0, ge=0.0, le=1.0)
    low_mood: float = Field(0.0, ge=0.0, le=1.0)


StrategyName = Literal[
    "supportive_listening",
    "validate_and_ground",
    "reflect_and_clarify",
    "collaborative_problem_solving",
    "ensure_immediate_safety",
    "crisis_support",
    "close_supportively",
]


class InteractionIntent(BaseModel):
    """Bounded interaction preferences; no raw text or inferred clinical facts."""

    model_config = ConfigDict(extra="forbid")
    primary: Literal[
        "small_talk",
        "venting",
        "seeking_clarification",
        "seeking_practical_help",
        "seeking_information",
        "ending",
        "unknown",
    ] = "unknown"
    advice_preference: Literal["requested", "declined", "unspecified"] = "unspecified"
    certainty: Literal["explicit", "inferred", "unknown"] = "unknown"
    source: Literal["current_turn", "unknown"] = "unknown"
    preference_source: Literal["current_turn", "recent_turn", "unknown"] = "unknown"
    feedback: Literal["helpful", "unhelpful", "unspecified"] = "unspecified"
    feedback_source: Literal["current_turn", "user_correction", "unknown"] = "unknown"
    evidence_codes: list[
        Literal[
            "explicit_listen_request",
            "explicit_no_advice",
            "explicit_advice_request",
            "explicit_clarification_request",
            "information_question",
            "explicit_closure",
            "greeting",
            "feedback_helpful",
            "feedback_unhelpful",
            "carried_preference",
        ]
    ] = Field(default_factory=list, max_length=10)


class CoordinationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[2] = 2
    proposed_strategy: StrategyName
    final_strategy: StrategyName
    previous_strategy: StrategyName | None = None
    reason_codes: list[
        Literal[
            "safety_priority",
            "explicit_closure",
            "advice_declined",
            "listen_requested",
            "advice_requested",
            "clarification_requested",
            "negative_feedback",
            "output_safety_override",
            "protocol_control_ignored",
            "protocol_boundary_response",
        ]
    ] = Field(default_factory=list, max_length=8)


class DecisionTrace(BaseModel):
    """Local execution facts; never accepted from the decision model."""

    source: Literal["rules", "model", "fallback", "safety_gate"] = "rules"
    latency_ms: float = Field(0.0, ge=0.0)
    fallback_reason: (
        Literal["timeout", "invalid_response", "api_error", "internal_error"] | None
    ) = None
    expression_fallback: bool = False
    output_safety_override: bool = False
    output_policy_override: bool = False
    protocol_version: Literal[1, 2] = 1
    coordination: CoordinationTrace | None = None


DimensionName = Literal["stress", "anxiety", "low_mood"]
ObservationSource = Literal[
    "system_estimate", "user_report", "user_correction", "unknown"
]


class UserStateReport(BaseModel):
    """Explicit, timestamped user input; never inferred from conversation."""

    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    emotion: dict[DimensionName, float] = Field(min_length=1, max_length=3)
    topics: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_report(self):
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Self-report requires an explicit timezone")
        if any(not 0 <= value <= 1 for value in self.emotion.values()):
            raise ValueError("Self-report scores must be finite values between 0 and 1")
        return self

    def to_state(self):
        return PsychologicalState(
            timestamp=self.timestamp,
            schema_version=4,
            estimator_source="user_report",
            confidence="user_reported",
            observed_dimensions=list(self.emotion),
            emotion=EmotionEstimate(**self.emotion),
            topics=self.topics,
        )


class PsychologicalState(BaseModel):
    """Estimated interaction state; this is not a clinical diagnosis."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: Literal[1, 2, 3, 4] = 1
    estimator_source: Literal[
        "legacy", "keyword_v1", "context_v2", "user_correction", "user_report"
    ] = "legacy"
    # Optional provenance extends older schemas without rewriting old records.
    timestamp_known: bool = True
    dimension_sources: dict[DimensionName, ObservationSource] = Field(
        default_factory=dict
    )
    topics_source: ObservationSource | None = None
    confidence: Literal["unknown", "low", "user_reported"] = "unknown"
    observed_dimensions: list[Literal["stress", "anxiety", "low_mood"]] = Field(
        default_factory=list
    )
    emotion: EmotionEstimate = Field(default_factory=EmotionEstimate)
    topics: list[str] = Field(default_factory=list)
    interaction_strategy: str = "supportive_listening"
    risk_level: RiskLevel = RiskLevel.LOW
    risk_signals: list[str] = Field(default_factory=list)
    summary: str = ""
    decision_trace: DecisionTrace | None = None
    interaction_intent: InteractionIntent | None = None
    context_evidence: list[ContextEvidence] | None = Field(default=None, max_length=64)


class PsychologicalMemoryEntry(BaseModel):
    scope: str
    state: PsychologicalState


class StrategyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    primary: StrategyName = "supportive_listening"
    secondary: Literal[
        "explore_context",
        "reflect_feelings",
        "offer_small_step",
        "check_safety_and_support",
        "encourage_human_support",
        "acknowledge_closure",
    ] = "explore_context"
    avoid: list[
        Literal[
            "diagnosis",
            "minimizing_feelings",
            "rapid_questioning",
            "debate",
            "overloading_instructions",
        ]
    ] = Field(
        default_factory=lambda: [
            "diagnosis",
            "minimizing_feelings",
        ],
        max_length=5,
    )


class BehaviorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expression: str = Field("neutral", min_length=1, max_length=64)
    motion: Literal["still", "gentle_nod"] = "still"
    gaze: Literal["attentive", "soft"] = "attentive"


class VoiceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    style: Literal["calm", "warm", "steady"] = "calm"
    speed: float = Field(1.0, ge=0.6, le=1.5)
    energy: float = Field(1.0, ge=0.5, le=1.5)


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategyDecision = Field(default_factory=StrategyDecision)
    behavior: BehaviorDecision = Field(default_factory=BehaviorDecision)
    voice: VoiceDecision = Field(default_factory=VoiceDecision)
    _trace: DecisionTrace = PrivateAttr(default_factory=DecisionTrace)

    @property
    def trace(self) -> DecisionTrace:
        return self._trace


class DecisionCapabilities(BaseModel):
    """Expressions are executable; the remaining controls are planning metadata."""

    expressions: list[str] = Field(default_factory=lambda: ["neutral"])
    motions: list[str] = Field(default_factory=lambda: ["still"])
    gazes: list[str] = Field(default_factory=list)
    applied_controls: list[str] = Field(default_factory=lambda: ["behavior.expression"])
    metadata_only_controls: list[str] = Field(
        default_factory=lambda: [
            "behavior.motion",
            "behavior.gaze",
            "voice.style",
            "voice.speed",
            "voice.energy",
        ]
    )


class DecisionContext(BaseModel):
    """Inputs supplied to the decision layer for a single interaction."""

    user_text: str
    protocol_control_detected: bool = False
    current_state: PsychologicalState
    recent_states: list[PsychologicalState] = Field(default_factory=list)
    safety: SafetyCheckResult
    capabilities: DecisionCapabilities = Field(default_factory=DecisionCapabilities)
    # Serialized StateTrend avoids a circular schema import.
    long_term_trend: dict | None = None
    interaction_intent: InteractionIntent = Field(default_factory=InteractionIntent)
    previous_strategy: StrategyName | None = None
