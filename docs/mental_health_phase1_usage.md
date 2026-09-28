# MentalHealthAgent Usage

For the current local setup and limitations, see [runtime guide](mental_health_runtime.md).

## 1. Choose and serve one adapter

Both training results in `D:/models` are PEFT LoRA adapters. Each must be loaded
with `D:/models/Qwen3-4B-Instruct-2507`; the adapter directory alone is not a
standalone model.

This workspace provides two LLaMA-Factory API examples:

- `config_templates/mental_health_sft_api.yaml`
- `config_templates/mental_health_orpo_api.yaml`

For example, serve the ORPO result in PowerShell:

```powershell
$env:API_HOST = "127.0.0.1"
$env:API_PORT = "8000"
$env:API_MODEL_NAME = "mental-health-orpo"
$env:API_KEY = "choose-a-local-api-key"
& "D:\模型微调\.venv-train\Scripts\llamafactory-cli.exe" api config_templates/mental_health_orpo_api.yaml
```

To serve the SFT result, change `API_MODEL_NAME` and use
`config_templates/mental_health_sft_api.yaml`. The two adapters were trained
independently against the same base model, so select one adapter per process for
this first integration.

## 2. Configure Open-LLM-VTuber

Create `conf.yaml` from the desired default template. In
`character_config.agent_config`, select the new Agent and fill its dialogue
connection:

```yaml
conversation_agent_choice: 'mental_health_agent'
agent_settings:
  mental_health_agent:
    dialogue:
      base_url: 'http://127.0.0.1:8000/v1'
      llm_api_key: 'the-same-key-used-by-the-api-server'
      model: 'mental-health-orpo'
      organization_id: null
      project_id: null
      temperature: 0.7
      interrupt_method: 'user'
    faster_first_response: true
    segment_method: 'pysbd'
    decision:
      enabled: false # Local rules until a separate decision endpoint is configured
    memory:
      storage_path: 'mental_health_memory/psychological_state.jsonl'
      recent_limit: 5
```

The `model` value must match `API_MODEL_NAME`. Keep API keys in the user-owned,
Git-ignored `conf.yaml`; do not put them in a tracked template.

## 3. Start the application

After installing the normal project dependencies, start Open-LLM-VTuber with:

```powershell
uv sync
uv run run_server.py
```

The current runtime path is:

`User input -> safety pre-check -> state estimate and recent state retrieval ->
Decision -> DialogueClient or escalation response -> safety post-check -> state persistence ->
SentenceOutput -> existing TTS and Live2D pipeline`.

The JSONL state file is separate from ordinary chat history and is ignored by
Git. It contains structured estimates and summaries, without raw user messages.

## 4. Run focused tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

These tests use a fake dialogue stream and do not require loading the 4B model.
