# Mental Health Agent Phase 1 Implementation Plan

> **For Claude:** Implement this plan task by task and verify each boundary.

**Goal:** Connect an already fine-tuned mental health dialogue model to the
existing Open-LLM-VTuber output pipeline through an OpenAI-compatible API.

**Architecture:** Add a dedicated dialogue client and an Agent implementation
that reuses `BasicMemoryAgent` for current memory, streaming, interruption, TTS,
and Live2D compatibility. Register typed configuration and factory creation.

**Tech Stack:** Python 3.10, Pydantic, OpenAI Python client, pytest/asyncio tests.

---

### Task 1: Dialogue boundary and Agent

- Create `src/open_llm_vtuber/mental_health/dialogue_client.py`.
- Create `src/open_llm_vtuber/agent/agents/mental_health_agent.py`.
- Add lightweight future-service protocols without implementing their behavior.
- Test streaming initialization with a fake dialogue client.

### Task 2: Configuration and factory registration

- Add typed mental health Agent settings.
- Register `mental_health_agent` in `AgentFactory`.
- Add safe placeholders to both default configuration templates.
- Test config validation and factory construction.

### Task 3: Verification and usage documentation

- Run focused tests, import checks, Ruff, and configuration validation.
- Document model-serving responsibility, setup, launch, and deferred features.
