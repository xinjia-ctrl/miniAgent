from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miniagent.audit_report import (
    SessionAuditReport,
    build_session_audit_report,
    render_audit_report,
)
from miniagent.bootstrap import RuntimeContainer, build_runtime_container
from miniagent.changes import ChangeStore, RevertResult
from miniagent.config import AgentConfig
from miniagent.engine import QueryEngine
from miniagent.memory import (
    MemoryItem,
    MemoryRecallHit,
    MemoryScope,
    MemoryStore,
    default_memory_path,
)
from miniagent.plugin_loader import PluginStatus, discover_plugins, install_plugin
from miniagent.storage import SessionRecord, SessionSummary


@dataclass
class MiniAgentApplication:
    """应用层入口，隔离 CLI 和底层 runtime 的装配细节。"""

    container: RuntimeContainer

    @classmethod
    def from_config(cls, config: AgentConfig) -> MiniAgentApplication:
        return cls(container=build_runtime_container(config))

    @property
    def config(self) -> AgentConfig:
        return self.container.config

    def create_engine(self, *, continue_session: bool = False) -> QueryEngine:
        session = self.container.storage.load_latest() if continue_session else None
        return self.container.create_engine(session=session)

    def load_latest_session(self) -> SessionRecord | None:
        return self.container.storage.load_latest()

    def inspect_latest_context(self) -> dict[str, object] | None:
        session = self.load_latest_session()
        if session is None:
            return None
        return {
            "session_id": session.id,
            "compact_summary": session.state.get("compact_summary"),
            "last_context": session.state.get("last_context"),
        }

    def list_sessions(self) -> list[SessionSummary]:
        return self.container.storage.list_sessions()

    def export_session(self, session_id: str | None = None) -> dict[str, object] | None:
        if session_id is None:
            latest = self.load_latest_session()
            if latest is None:
                return None
            session_id = latest.id
        return self.container.storage.export(session_id)

    def audit_report(self, session_id: str, *, timeline_limit: int = 80) -> SessionAuditReport:
        return build_session_audit_report(
            storage=self.container.storage,
            audit_path=self.config.audit_path,
            session_id=session_id,
            timeline_limit=timeline_limit,
        )

    def render_audit_report(self, session_id: str, *, timeline_limit: int = 80) -> str:
        return render_audit_report(self.audit_report(session_id, timeline_limit=timeline_limit))

    def describe_changes(self, change_id: str | None = None, *, limit: int = 20) -> str:
        return ChangeStore(self.config.resolved_data_dir).describe(change_id, limit=limit)

    def revert_change(self, change_id: str) -> RevertResult:
        return ChangeStore(self.config.resolved_data_dir).revert(change_id, cwd=self.config.cwd)

    def memory_store(self) -> MemoryStore:
        return MemoryStore(
            default_memory_path(data_dir=self.config.resolved_data_dir, cwd=self.config.cwd)
        )

    def list_memories(self, *, scope: MemoryScope | None = None) -> list[MemoryItem]:
        return self.memory_store().list_memories(
            scope=scope,
            project=self.project_key,
        )

    def search_memories(
        self,
        query: str,
        *,
        scope: MemoryScope | None = None,
        limit: int = 20,
        tags: list[str] | None = None,
    ) -> list[MemoryRecallHit]:
        return self.memory_store().recall_hits(
            query,
            limit=limit,
            tags=tags,
            scope=scope,
            project=self.project_key,
        )

    def remember_memory(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        importance: float = 1,
        scope: MemoryScope = "project",
    ) -> MemoryItem:
        return self.memory_store().remember(
            content,
            tags=tags,
            importance=importance,
            scope=scope,
            project=self.project_key if scope == "project" else None,
            source="cli:memory",
        )

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        importance: float | None = None,
        scope: MemoryScope | None = None,
    ) -> MemoryItem | None:
        next_scope = scope
        project = self.project_key if next_scope == "project" else None
        return self.memory_store().update(
            memory_id,
            content=content,
            tags=tags,
            importance=importance,
            scope=scope,
            project=project,
            source="cli:memory",
        )

    def delete_memory(self, memory_id: str) -> bool:
        return self.memory_store().delete(memory_id)

    @property
    def project_key(self) -> str:
        return str(Path(self.config.cwd).resolve())

    def list_tools(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for name in self.container.registry.names():
            tool = self.container.registry.get(name)
            metadata = self.container.registry.metadata(name)
            items.append(
                {
                    "name": name,
                    "description": tool.description,
                    "source": metadata.get("source", "builtin"),
                    "plugin": metadata.get("plugin"),
                    "kind": metadata.get("kind", "builtin"),
                    "declared_permissions": metadata.get("declared_permissions", []),
                }
            )
        return items

    def inspect_tool(self, name: str) -> dict[str, object]:
        tool = self.container.registry.get(name)
        return {
            "name": name,
            "description": tool.description,
            "schema": tool.schema(),
            "metadata": self.container.registry.metadata(name),
        }

    def list_plugins(self) -> list[PluginStatus]:
        loaded = {status.path: status for status in self.container.plugin_statuses}
        discovered = discover_plugins(
            data_dir=self.config.resolved_data_dir,
            cwd=self.config.cwd,
        )
        return [loaded.get(status.path, status) for status in discovered]

    def install_plugin(self, source: str | Path, *, force: bool = False) -> PluginStatus:
        return install_plugin(
            source,
            data_dir=self.config.resolved_data_dir,
            cwd=self.config.cwd,
            force=force,
        )

    def diagnostics(self) -> dict[str, str]:
        config = self.config
        return {
            "cwd": config.cwd,
            "data_dir": str(config.resolved_data_dir),
            "audit_path": str(config.audit_path),
            "provider": config.model.provider,
            "model": config.model.model,
        }
