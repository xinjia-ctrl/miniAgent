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
    provider: str = "fake",
    model: str = "fake",
    base_url: str = "https://api.openai.com/v1/chat/completions",
    permission_mode: str = "default",
    non_interactive: bool = True,
    debug: bool = False,
) -> AgentConfig:
    return default_config(
        cwd=cwd,
        model=ModelSettings(provider=provider, model=model, base_url=base_url),
        permission_mode=permission_mode,
        non_interactive=non_interactive,
        debug=debug,
    )


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
