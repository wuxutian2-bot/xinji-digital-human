"""Current first-person observations only; zero is not an observed absence."""

from .context_signals import context_clauses
from .state_estimator import KeywordStateEstimator


class ContextStateEstimator(KeywordStateEstimator):
    async def estimate(self, text, safety):
        clauses = context_clauses(text)
        observed = [
            c.text
            for c in clauses
            if c.evidence.subject == "self"
            and c.evidence.temporality == "current"
            and c.evidence.assertion == "affirmed"
            and not c.evidence.uncertainty
        ]
        state = await super().estimate("。".join(observed), safety)
        state.schema_version = 3
        state.estimator_source = "context_v2"
        state.context_evidence = [c.evidence for c in clauses][:64]
        return state
