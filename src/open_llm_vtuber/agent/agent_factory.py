from typing import Literal, Optional, Type

from loguru import logger

from ..mcpp.tool_executor import ToolExecutor
from ..mcpp.tool_manager import ToolManager
from ..mental_health.dialogue_client import DialogueClient
from ..mental_health.decision_client import (
    FallbackDecisionClient,
    OpenAICompatibleDecisionClient,
    RuleBasedDecisionClient,
)
from ..mental_health.memory_service import (
    DisabledPsychologicalMemoryService,
    JsonlPsychologicalMemoryService,
)
from ..mental_health.sqlite_memory import SqlitePsychologicalMemoryService
from ..mental_health.safety_guard import RuleBasedSafetyGuard
from ..mental_health.state_estimator import KeywordStateEstimator
from ..mental_health.context_safety import ContextSafetyGuard
from ..mental_health.context_state import ContextStateEstimator
from .agents.agent_interface import AgentInterface
from .agents.basic_memory_agent import BasicMemoryAgent
from .agents.hume_ai import HumeAIAgent
from .agents.letta_agent import LettaAgent
from .agents.mental_health_agent import MentalHealthAgent
from .stateless_llm_factory import LLMFactory as StatelessLLMFactory


class AgentFactory:
    @staticmethod
    def create_agent(
        conversation_agent_choice: str,
        agent_settings: dict,
        llm_configs: dict,
        system_prompt: str,
        live2d_model=None,
        tts_preprocessor_config=None,
        **kwargs,
    ) -> Type[AgentInterface]:
        """Create an agent based on the configuration.

        Args:
            conversation_agent_choice: The type of agent to create
            agent_settings: Settings for different types of agents
            llm_configs: Pool of LLM configurations
            system_prompt: The system prompt to use
            live2d_model: Live2D model instance for expression extraction
            tts_preprocessor_config: Configuration for TTS preprocessing
            **kwargs: Additional arguments
        """
        logger.info(f"Initializing agent: {conversation_agent_choice}")

        if conversation_agent_choice == "mental_health_agent":
            settings: dict = agent_settings.get("mental_health_agent", {})
            dialogue_settings = dict(settings.get("dialogue") or {})
            if not dialogue_settings:
                raise ValueError("Mental health dialogue configuration not found")

            interrupt_method: Literal["system", "user"] = dialogue_settings.pop(
                "interrupt_method", "user"
            )
            dialogue_client = DialogueClient(**dialogue_settings)
            decision_settings = dict(settings.get("decision") or {})
            decision_enabled = decision_settings.pop("enabled", False)
            if decision_enabled:
                decision_client = FallbackDecisionClient(
                    OpenAICompatibleDecisionClient(**decision_settings)
                )
            else:
                decision_client = RuleBasedDecisionClient()
            memory_settings = dict(settings.get("memory") or {})
            if not memory_settings.get("enabled", True):
                memory_service = DisabledPsychologicalMemoryService()
            elif memory_settings.get("mode", "history") == "local_user":
                system = kwargs.get("system_config", {})
                if system.get("host") not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                } or system.get("enable_proxy", False):
                    raise ValueError(
                        "Local-user memory requires a loopback server without group proxy"
                    )
                memory_service = SqlitePsychologicalMemoryService(
                    memory_settings.get(
                        "sqlite_path", "mental_health_memory/states.sqlite3"
                    ),
                    memory_settings.get("user_id") or "",
                    memory_settings.get("recent_limit", 5),
                    trend_settings=memory_settings.get("trend"),
                )
            else:
                memory_service = JsonlPsychologicalMemoryService(
                    storage_path=memory_settings.get(
                        "storage_path",
                        "mental_health_memory/psychological_state.jsonl",
                    ),
                    recent_limit=memory_settings.get("recent_limit", 5),
                )
            return MentalHealthAgent(
                dialogue_client=dialogue_client,
                decision_client=decision_client,
                safety_guard=ContextSafetyGuard()
                if settings.get("context_version", 1) == 2
                else RuleBasedSafetyGuard(),
                state_estimator=ContextStateEstimator()
                if settings.get("context_version", 1) == 2
                else KeywordStateEstimator(),
                memory_service=memory_service,
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=settings.get("faster_first_response", True),
                segment_method=settings.get("segment_method", "pysbd"),
                interrupt_method=interrupt_method,
                expression_enabled=settings.get("expression_enabled", True),
                supported_voice_controls=kwargs.get(
                    "tts_supported_controls", frozenset()
                ),
                behavior_frontend_enabled=kwargs.get("system_config", {}).get(
                    "frontend_dir", "frontend"
                )
                == "frontend-src/dist/web",
                decision_protocol_version=decision_settings.get("protocol_version", 2),
            )

        if conversation_agent_choice == "basic_memory_agent":
            # Get the LLM provider choice from agent settings
            basic_memory_settings: dict = agent_settings.get("basic_memory_agent", {})
            llm_provider: str = basic_memory_settings.get("llm_provider")

            if not llm_provider:
                raise ValueError("LLM provider not specified for basic memory agent")

            # Get the LLM config for this provider
            llm_config: dict = llm_configs.get(llm_provider)
            interrupt_method: Literal["system", "user"] = llm_config.pop(
                "interrupt_method", "user"
            )

            if not llm_config:
                raise ValueError(
                    f"Configuration not found for LLM provider: {llm_provider}"
                )

            # Create the stateless LLM
            llm = StatelessLLMFactory.create_llm(
                llm_provider=llm_provider, system_prompt=system_prompt, **llm_config
            )

            tool_prompts = kwargs.get("system_config", {}).get("tool_prompts", {})

            # Extract MCP components/data needed by BasicMemoryAgent from kwargs
            tool_manager: Optional[ToolManager] = kwargs.get("tool_manager")
            tool_executor: Optional[ToolExecutor] = kwargs.get("tool_executor")
            mcp_prompt_string: str = kwargs.get("mcp_prompt_string", "")

            # Create the agent with the LLM and live2d_model
            return BasicMemoryAgent(
                llm=llm,
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=basic_memory_settings.get(
                    "faster_first_response", True
                ),
                segment_method=basic_memory_settings.get("segment_method", "pysbd"),
                use_mcpp=basic_memory_settings.get("use_mcpp", False),
                interrupt_method=interrupt_method,
                tool_prompts=tool_prompts,
                tool_manager=tool_manager,
                tool_executor=tool_executor,
                mcp_prompt_string=mcp_prompt_string,
            )

        elif conversation_agent_choice == "mem0_agent":
            from .agents.mem0_llm import LLM as Mem0LLM

            mem0_settings = agent_settings.get("mem0_agent", {})
            if not mem0_settings:
                raise ValueError("Mem0 agent settings not found")

            # Validate required settings
            required_fields = ["base_url", "model", "mem0_config"]
            for field in required_fields:
                if field not in mem0_settings:
                    raise ValueError(
                        f"Missing required field '{field}' in mem0_agent settings"
                    )

            return Mem0LLM(
                user_id=kwargs.get("user_id", "default"),
                system=system_prompt,
                live2d_model=live2d_model,
                **mem0_settings,
            )

        elif conversation_agent_choice == "hume_ai_agent":
            settings = agent_settings.get("hume_ai_agent", {})
            return HumeAIAgent(
                api_key=settings.get("api_key"),
                host=settings.get("host", "api.hume.ai"),
                config_id=settings.get("config_id"),
                idle_timeout=settings.get("idle_timeout", 15),
            )

        elif conversation_agent_choice == "letta_agent":
            settings = agent_settings.get("letta_agent", {})
            return LettaAgent(
                live2d_model=live2d_model,
                id=settings.get("id"),
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=settings.get("faster_first_response"),
                segment_method=settings.get("segment_method"),
                host=settings.get("host"),
                port=settings.get("port"),
            )

        else:
            raise ValueError(f"Unsupported agent type: {conversation_agent_choice}")
