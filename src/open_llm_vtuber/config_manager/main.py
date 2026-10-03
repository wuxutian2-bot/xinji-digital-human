# config_manager/main.py
from pydantic import BaseModel, Field, model_validator
from typing import Dict, ClassVar

from .system import SystemConfig
from .character import CharacterConfig
from .live import LiveConfig
from .i18n import I18nMixin, Description


class Config(I18nMixin, BaseModel):
    """
    Main configuration for the application.
    """

    system_config: SystemConfig = Field(default=None, alias="system_config")
    character_config: CharacterConfig = Field(..., alias="character_config")
    live_config: LiveConfig = Field(default=LiveConfig(), alias="live_config")

    @model_validator(mode="after")
    def trial_profile_boundary(self):
        if self.system_config and self.system_config.trial_mode:
            agent = self.character_config.agent_config
            settings = agent.agent_settings.mental_health_agent
            if (
                self.system_config.host not in {"localhost", "127.0.0.1", "::1"}
                or self.system_config.enable_proxy
                or agent.conversation_agent_choice != "mental_health_agent"
                or not settings
                or not settings.memory.enabled
                or settings.memory.mode != "local_user"
                or settings.memory.trend.version != "daily_v2"
            ):
                raise ValueError(
                    "Trial mode requires loopback, no proxy, and mental_health_agent with local_user daily_v2 memory"
                )
        return self

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "system_config": Description(
            en="System configuration settings", zh="系统配置设置"
        ),
        "character_config": Description(
            en="Character configuration settings", zh="角色配置设置"
        ),
        "live_config": Description(
            en="Live streaming platform integration settings", zh="直播平台集成设置"
        ),
    }
