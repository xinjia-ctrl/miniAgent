from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


PermissionModeName = Literal["default", "accept_edits", "plan", "bypass"]
ModelProviderName = Literal["fake", "openai-compatible"]


class ModelSettings(BaseModel):
    provider: ModelProviderName = "fake"
    model: str = "fake"
    base_url: str = "https://api.openai.com/v1/chat/completions"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 60


class AgentConfig(BaseModel):
    cwd: str = Field(default_factory=lambda: str(Path.cwd()))
    data_dir: str | None = None
    model: ModelSettings = Field(default_factory=ModelSettings)
    permission_mode: PermissionModeName = "default"
    max_turns: int = 8
    max_result_chars: int = 6000
    context_token_budget: int = 8000
    non_interactive: bool = True
    debug: bool = False

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return Path(self.cwd) / ".pycode_agent"

    @property
    def audit_path(self) -> Path:
        return self.resolved_data_dir / "audit.jsonl"


def default_config(cwd: str | Path | None = None, **overrides: object) -> AgentConfig:
    values = {"cwd": str(cwd or Path.cwd())}
    model_name = os.environ.get("PYCODE_AGENT_MODEL")
    provider = os.environ.get("PYCODE_AGENT_PROVIDER")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model_values: dict[str, object] = {}
    if model_name:
        model_values["model"] = model_name
        if model_name != "fake":
            model_values["provider"] = "openai-compatible"
    if provider:
        model_values["provider"] = provider
    if base_url:
        model_values["base_url"] = base_url
    if model_values:
        values["model"] = ModelSettings(**model_values)
    values.update(overrides)
    return AgentConfig(**values)
