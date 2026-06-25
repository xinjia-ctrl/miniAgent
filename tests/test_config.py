from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from miniagent.bootstrap import build_agent_config
from miniagent.config import (
    PersistedSettings,
    project_config_path,
    save_persisted_settings,
    user_config_path,
)


def test_user_config_applies_in_another_project(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "user-config"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(config_dir))
    save_persisted_settings(
        user_config_path(),
        PersistedSettings(
            provider="openai-compatible",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/chat/completions",
            permission_mode="accept_edits",
        ),
    )

    config = build_agent_config(cwd=project)

    assert config.model.provider == "openai-compatible"
    assert config.model.model == "deepseek-v4-flash"
    assert config.model.base_url == "https://api.deepseek.com/chat/completions"
    assert config.permission_mode == "accept_edits"


def test_project_config_overrides_user_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    project = tmp_path / "project"
    project.mkdir()
    save_persisted_settings(
        user_config_path(),
        PersistedSettings(model="deepseek-v4-flash", permission_mode="accept_edits"),
    )
    save_persisted_settings(
        project_config_path(project),
        PersistedSettings(model="project-model", permission_mode="plan"),
    )

    config = build_agent_config(cwd=project)

    assert config.model.model == "project-model"
    assert config.permission_mode == "plan"


def test_cli_values_override_project_user_and_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    monkeypatch.setenv("MINIAGENT_MODEL", "environment-model")
    project = tmp_path / "project"
    project.mkdir()
    save_persisted_settings(user_config_path(), PersistedSettings(model="user-model"))
    save_persisted_settings(project_config_path(project), PersistedSettings(model="project-model"))

    config = build_agent_config(cwd=project, model="cli-model")

    assert config.model.model == "cli-model"


def test_explicit_fake_model_switches_provider_back_to_fake(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    save_persisted_settings(
        user_config_path(),
        PersistedSettings(provider="openai-compatible", model="deepseek-v4-flash"),
    )

    config = build_agent_config(cwd=tmp_path, model="fake")

    assert config.model.provider == "fake"
    assert config.model.model == "fake"


def test_environment_is_used_when_no_config_file_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    monkeypatch.setenv("MINIAGENT_PROVIDER", "openai-compatible")
    monkeypatch.setenv("MINIAGENT_MODEL", "environment-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/chat/completions")

    config = build_agent_config(cwd=tmp_path)

    assert config.model.provider == "openai-compatible"
    assert config.model.model == "environment-model"
    assert config.model.base_url == "https://example.com/chat/completions"


def test_persisted_config_never_contains_api_key_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    path = user_config_path()
    save_persisted_settings(
        path,
        PersistedSettings(
            provider="openai-compatible",
            model="deepseek-v4-flash",
            api_key_env="OPENAI_API_KEY",
        ),
    )

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["api_key_env"] == "OPENAI_API_KEY"
    assert "api_key" not in raw


def test_persisted_config_rejects_plaintext_api_key() -> None:
    with pytest.raises(ValidationError):
        PersistedSettings.model_validate({"api_key": "secret"})
