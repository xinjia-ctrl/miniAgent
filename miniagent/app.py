from __future__ import annotations

from dataclasses import dataclass

from miniagent.bootstrap import RuntimeContainer, build_runtime_container
from miniagent.config import AgentConfig
from miniagent.engine import QueryEngine
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

    def diagnostics(self) -> dict[str, str]:
        config = self.config
        return {
            "cwd": config.cwd,
            "data_dir": str(config.resolved_data_dir),
            "audit_path": str(config.audit_path),
            "provider": config.model.provider,
            "model": config.model.model,
        }
