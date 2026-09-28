"""Dialogue-model client for the mental health conversation agent."""

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from openai import NOT_GIVEN, NotGiven

from ..agent.stateless_llm.openai_compatible_llm import AsyncLLM
from ..agent.stateless_llm.stateless_llm_interface import StatelessLLMInterface


class DialogueClient(StatelessLLMInterface):
    """Call the fine-tuned dialogue model through an OpenAI-compatible API.

    Model loading is intentionally outside the application. A serving process
    must load the base model plus the selected adapter and expose ``model`` at
    ``base_url``.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        llm_api_key: str,
        organization_id: str | None = None,
        project_id: str | None = None,
        temperature: float = 0.7,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Mental health dialogue base_url must not be empty")
        if not model.strip():
            raise ValueError("Mental health dialogue model must not be empty")

        self.model = model
        self.base_url = base_url
        self._client = AsyncLLM(
            model=model,
            base_url=base_url,
            llm_api_key=llm_api_key,
            organization_id=organization_id,
            project_id=project_id,
            temperature=temperature,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | NotGiven = NOT_GIVEN,
    ) -> AsyncIterator[str]:
        """Stream dialogue chunks without storing conversation state."""
        # LLaMA-Factory requires alternating user/assistant turns. Interrupt
        # markers and a cancelled generation can leave adjacent user messages.
        normalized = self._merge_adjacent_turns(messages)
        async for chunk in self._client.chat_completion(normalized, system, tools):
            yield chunk

    @staticmethod
    def _merge_adjacent_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for message in deepcopy(messages):
            if (
                result
                and message["role"] in {"user", "assistant"}
                and result[-1]["role"] == message["role"]
            ):
                previous = result[-1]["content"]
                current = message["content"]
                if isinstance(previous, str) and isinstance(current, str):
                    result[-1]["content"] = previous + "\n\n" + current
                else:

                    def parts(value):
                        return (
                            [{"type": "text", "text": value}]
                            if isinstance(value, str)
                            else value
                        )

                    result[-1]["content"] = parts(previous) + parts(current)
            else:
                result.append(message)
        return result
