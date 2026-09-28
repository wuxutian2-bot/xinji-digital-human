# Safety, State, and Memory Phase 2 Implementation Plan

**Goal:** Add mandatory safety gates, non-diagnostic psychological state schemas,
and simple persistent state memory to `MentalHealthAgent`.

**Architecture:** Use deterministic local safety and state-estimation baselines so
the pipeline cannot skip safety checks. Store structured state records in a
separate scoped JSONL file and inject only summarized trends into dialogue context.

**Tech Stack:** Python 3.10, Pydantic, JSONL, existing Agent transformers.

---

1. Add schemas for safety results, emotion estimates, and psychological state.
2. Implement mandatory input/output safety checks and fixed escalation responses.
3. Implement a keyword-based non-clinical state estimator.
4. Implement scoped JSONL persistence with bounded recent retrieval.
5. Wire the services around dialogue generation in `MentalHealthAgent`.
6. Register memory settings in typed configuration and templates.
7. Test safety bypass prevention, output rewriting, schemas, persistence, and the
   existing SentenceOutput path.
