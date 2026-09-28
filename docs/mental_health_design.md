# Mental Health Cognitive Layer Design

This document records the design constraints supplied for this repository and the
phased implementation decisions. The original project-specific design document
was not present in the upstream Open-LLM-VTuber repository.

## Goal

Add a `MentalHealthAgent` that calls an already fine-tuned dialogue model through
an OpenAI-compatible API while preserving Open-LLM-VTuber's existing streaming,
interruption, chat-history, `SentenceOutput`, TTS, and Live2D paths.

The local model artifacts are PEFT LoRA adapters. The inference server is
responsible for loading the base model and the selected adapter and exposing it
under a configured model name. The application does not load model weights.

## Original repository and gap analysis

The upstream v1 repository initially had:

- `AgentInterface` and `AgentFactory` under `src/open_llm_vtuber/agent/`.
- `BasicMemoryAgent`, which owns conversation memory, interruption handling, and
  the streaming transformer chain.
- `openai_compatible_llm.AsyncLLM`, which uses the OpenAI Python client.
- Pydantic configuration models in `src/open_llm_vtuber/config_manager/`.
- `SentenceOutput` and `Actions` in `agent/output_types.py`.
- `process_agent_output` in `conversations/conversation_utils.py`, followed by
  `TTSManager` and the existing WebSocket/Live2D messages.

The original upstream architecture agrees with the design on using an Agent factory,
an OpenAI-compatible dialogue backend, and the existing output pipeline. The
repository differs from older assumptions in these ways:

- There is no generic `process_agent_output` hook inside an Agent. Output is
  consumed by both single and group conversation handlers.
- Original upstream `Actions` supports expressions, pictures, and sounds. Motion, gaze,
  voice style, speed, energy, and strategy are not represented yet.
- Live2D expressions are currently inferred from text emotion tags by the
  `actions_extractor` transformer.
- Ordinary conversation history is present, while long-term psychological state
  storage is not.

## Phase 1 design

`MentalHealthAgent` extends `BasicMemoryAgent` so it stays compatible with the
current Agent interface and output pipeline. A dedicated `DialogueClient`
encapsulates the OpenAI-compatible backend and is injected into the Agent.

The configuration is scoped to `agent_settings.mental_health_agent.dialogue`:

- `base_url`: OpenAI-compatible API root, normally ending in `/v1`.
- `model`: served model or adapter name exposed by the inference server.
- `llm_api_key`: API key; a local server may accept a placeholder.
- `temperature`, `organization_id`, `project_id`, and `interrupt_method`.

The phase 1 call chain is:

`BatchInput -> MentalHealthAgent -> DialogueClient -> API token stream -> existing
sentence/actions/display/TTS transformers -> SentenceOutput -> existing
conversation/TTS/Live2D pipeline`.

## Phase 2 safety, state, and memory

Phase 2 adds a deterministic `RuleBasedSafetyGuard` before and after dialogue
generation. High and critical input bypasses the dialogue model and produces a
fixed escalation response. Normal generated text is buffered and checked before
any part is passed to `SentenceOutput`, TTS, or Live2D.

`KeywordStateEstimator` produces bounded, non-diagnostic estimates for stress,
anxiety, and low mood, plus topics, risk level, interaction strategy, and a short
summary. `JsonlPsychologicalMemoryService` stores these records separately from
chat history. Records are scoped by configuration and history ID. Only structured
summaries and recent aggregate trends are supplied to the dialogue model; raw user
messages are not copied into this store. Before a history ID is assigned, each
Agent instance uses an isolated random session scope to prevent cross-session
state sharing.

The current call chain is:

`BatchInput -> mandatory safety pre-check -> state estimate -> recent state
retrieval -> DialogueClient or escalation response -> mandatory safety post-check
-> state persistence -> existing SentenceOutput/TTS/Live2D pipeline`.

## Phase 3 structured decisions and runtime integration

The default `RuleBasedDecisionClient` produces strategy, behavior and voice in a
single `DecisionResult`. The optional `OpenAICompatibleDecisionClient` makes one
request (SDK retries disabled) within a total deadline. All fields must be present
and valid; `FallbackDecisionClient` uses local rules on network or validation
failure. No independent remote decision model is configured in this workspace yet.

`MentalHealthAgent` converts Decision expression names directly through the
Live2D model's emotion map. Dialogue emotion tags do not control actions. Unknown
expression names use neutral when the avatar provides that mapping. Post-gate
rewrites/blocks reset actions to conservative defaults. Decisions are local to a
single generator invocation and the selected strategy is persisted in state.

The phase 3 chain is:

`Input -> safety pre-check -> state estimate -> scoped recent state retrieval ->
Decision (local rules or one API call) -> DialogueClient -> safety post-check ->
state persistence -> direct Decision Actions -> SentenceOutput -> TTS / Live2D`.

High/critical input uses a fixed safety response and bypasses both model calls.

Each WebSocket connection creates its own mental-health Agent while reusing the
existing ASR/TTS/Live2D engines. Psychological scope is captured at turn start so
a history switch during generation does not move that state record to a new
history. The original JSONL mode remains history-scoped and intended for a single
backend process. The new local-user mode below provides cross-history continuity.

Runtime fixes retain the original infrastructure: optional ASR disabling for
text input, bundled FFmpeg decoding when system tools are unavailable, and waiting
for ordered audio delivery before notifying playback completion. Completion is
sent once and its acknowledgment is registered first. These changes address
observed local startup and playback issues.

## Tasks 3–5 implementation (2026-09-22)

`frontend-src/` preserves the matching upstream source and adds bounded gentle-nod
and gaze controls to the Live2D update loop. Controls begin with audio playback
and are cleared on interruption. The web backend serves its built `dist/web`.
Edge TTS applies speed independently to each utterance; unsupported style and
energy are explicitly reported as fallbacks. Human perception checks are pending.

The local configuration now enables stable-user SQLite memory. Identity is bound
by the server configuration and restricted to a loopback, non-proxy deployment;
all local clients share that profile. This is not multi-user authentication.
Schema v2 records observed dimensions, source and uncertainty. Trends compare
7-day windows and distinguish missing evidence from low measured distress. Only
sufficiently observed trends affect the rule decision. Explicit CLI operations
support inspection, corrections, scoped deletion and idempotent JSONL migration.
Raw chat records retain their separate lifecycle.

Sixteen synthetic evaluation cases exercise the actual agent with either stub or
real dialogue, including memory/expression ablations with mandatory Safety kept
enabled. Reports retain source and fixture hashes, timings and decision traces.
Human quality scores and playback completion remain unset for script-only runs.
The local SenseVoice model is installed and ASR enabled; microphone acceptance is
deferred. The initial Safety and keyword-state baselines still need representative
evaluation, and the independent Decision model has not been deployed.

See `mental_health_runtime.md` for the current launch and verification procedure.
