"""Extension contracts for cognitive-layer services."""

from typing import Protocol

from .schemas import (
    DecisionContext,
    DecisionResult,
    PsychologicalState,
    SafetyCheckResult,
)


class SafetyGuard(Protocol):
    async def check_input(self, text: str) -> SafetyCheckResult: ...

    async def check_output(self, text: str) -> SafetyCheckResult: ...


class PsychologicalStateEstimator(Protocol):
    async def estimate(
        self, text: str, safety: SafetyCheckResult
    ) -> PsychologicalState: ...


class PsychologicalMemoryService(Protocol):
    async def retrieve_recent(
        self, scope: str, limit: int | None = None
    ) -> list[PsychologicalState]: ...

    async def append(self, scope: str, state: PsychologicalState) -> None: ...


class DecisionClient(Protocol):
    async def decide(self, context: DecisionContext) -> DecisionResult: ...
