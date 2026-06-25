from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miniagent.audit import AuditLogger
from miniagent.config import AgentConfig, ModelSettings, default_config
from miniagent.context import ContextBuilder
from miniagent.engine import QueryEngine
from miniagent.model import ModelClient, create_model_router
from miniagent.permissions import PermissionManager
from miniagent.plugin_loader import PluginStatus, load_plugins
from miniagent.storage import SessionRecord, SessionStorage
from miniagent.tool_base import ToolRegistry
from miniagent.tools import builtin_registry


@dataclass
class RuntimeContainer:
    """集中保存一次应用运行需要的核心依赖。"""

    config: AgentConfig
    model_client: ModelClient
    registry: ToolRegistry
    storage: SessionStorage
    context_builder: ContextBuilder
    permission_manager: PermissionManager
    audit_logger: AuditLogger
    plugin_statuses: list[PluginStatus]

    def create_engine(self, session: SessionRecord | None = None) -> QueryEngine:
        return QueryEngine(
            config=self.config,
            model_client=self.model_client,
            registry=self.registry,
            storage=self.storage,
            context_builder=self.context_builder,
            permission_manager=self.permission_manager,
            audit_logger=self.audit_logger,
            session=session,
        )


def build_agent_config(
    *,
    cwd: str | Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    permission_mode: str | None = None,
    non_interactive: bool = True,
    debug: bool = False,
) -> AgentConfig:
    base = default_config(cwd=cwd)
    model_values = base.model.model_dump()
    effective_provider = provider
    if effective_provider is None and model == "fake":
        effective_provider = "fake"
    elif effective_provider is None and model and base.model.provider == "fake":
        effective_provider = "openai-compatible"
    explicit_model_values = {
        "provider": effective_provider,
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
    }
    model_values.update(
        {key: value for key, value in explicit_model_values.items() if value is not None}
    )
    values = base.model_dump()
    values.update(
        {
            "model": ModelSettings.model_validate(model_values),
            "permission_mode": permission_mode or base.permission_mode,
            "non_interactive": non_interactive,
            "debug": debug,
        }
    )
    return AgentConfig.model_validate(values)


def build_runtime_container(config: AgentConfig) -> RuntimeContainer:
    registry = builtin_registry()
    plugin_statuses = load_plugins(
        registry,
        data_dir=config.resolved_data_dir,
        cwd=config.cwd,
    )
    return RuntimeContainer(
        config=config,
        model_client=create_model_router(config.model),
        registry=registry,
        storage=SessionStorage(config.resolved_data_dir),
        context_builder=ContextBuilder(),
        permission_manager=PermissionManager(non_interactive=config.non_interactive),
        audit_logger=AuditLogger(config.audit_path),
        plugin_statuses=plugin_statuses,
    )
