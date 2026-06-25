from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PermissionModeName = Literal["default", "accept_edits", "plan", "bypass"]
ModelProviderName = Literal["fake", "openai-compatible", "anthropic-compatible"]
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1/chat/completions"


class ModelSettings(BaseModel):
    provider: ModelProviderName = "fake"
    model: str = "fake"
    base_url: str = DEFAULT_OPENAI_BASE_URL
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 60
    max_retries: int = 1
    max_output_tokens: int = 4096
    anthropic_version: str = "2023-06-01"


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
        return Path(self.cwd) / ".miniagent"

    @property
    def audit_path(self) -> Path:
        return self.resolved_data_dir / "audit.jsonl"


class PersistedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ModelProviderName | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    permission_mode: PermissionModeName | None = None


def user_config_dir() -> Path:
    override = os.environ.get("MINIAGENT_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".miniagent"


def user_config_path() -> Path:
    return user_config_dir() / "config.json"


def project_config_path(cwd: str | Path) -> Path:
    return Path(cwd).resolve(strict=False) / ".miniagent" / "config.json"


def load_persisted_settings(path: str | Path) -> PersistedSettings | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        return PersistedSettings.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"配置文件无效：{target}\n{exc}") from exc


def save_persisted_settings(path: str | Path, settings: PersistedSettings) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json", exclude_none=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def delete_persisted_settings(path: str | Path) -> bool:
    target = Path(path)
    if not target.exists():
        return False
    try:
        target.unlink()
    except PermissionError:
        try:
            target.chmod(stat.S_IWRITE)
            target.unlink()
        except PermissionError:
            target.write_text("{}\n", encoding="utf-8")
    return True


def effective_persisted_settings(cwd: str | Path) -> PersistedSettings:
    values: dict[str, object] = {}
    environment = _environment_settings()
    if environment:
        values.update(environment.model_dump(exclude_none=True))
    user_settings = load_persisted_settings(user_config_path())
    if user_settings:
        values.update(user_settings.model_dump(exclude_none=True))
    project_settings = load_persisted_settings(project_config_path(cwd))
    if project_settings:
        values.update(project_settings.model_dump(exclude_none=True))
    return PersistedSettings.model_validate(values)


def default_config(cwd: str | Path | None = None, **overrides: object) -> AgentConfig:
    resolved_cwd = Path(cwd or Path.cwd()).resolve(strict=False)
    persisted = effective_persisted_settings(resolved_cwd)
    values: dict[str, object] = {"cwd": str(resolved_cwd)}
    model_values = {
        key: value
        for key, value in {
            "provider": persisted.provider,
            "model": persisted.model,
            "base_url": persisted.base_url,
            "api_key_env": persisted.api_key_env,
        }.items()
        if value is not None
    }
    if model_values:
        values["model"] = ModelSettings(**model_values)
    if persisted.permission_mode:
        values["permission_mode"] = persisted.permission_mode
    values.update(overrides)
    return AgentConfig(**values)


def _environment_settings() -> PersistedSettings:
    model = os.environ.get("MINIAGENT_MODEL")
    provider = os.environ.get("MINIAGENT_PROVIDER")
    if model and model != "fake" and not provider:
        provider = "openai-compatible"
    return PersistedSettings(
        provider=provider,
        model=model,
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key_env=os.environ.get("MINIAGENT_API_KEY_ENV"),
        permission_mode=os.environ.get("MINIAGENT_PERMISSION_MODE"),
    )
