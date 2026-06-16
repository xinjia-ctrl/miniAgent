from __future__ import annotations

from miniagent.app import MiniAgentApplication
from miniagent.bootstrap import build_agent_config, build_runtime_container
from miniagent.messages import user_text
from miniagent.storage import SessionRecord


def test_runtime_container_creates_engine_with_shared_dependencies(tmp_path) -> None:
    config = build_agent_config(cwd=tmp_path, non_interactive=False)
    container = build_runtime_container(config)

    engine = container.create_engine()

    assert engine.config is config
    assert engine.model_client is container.model_client
    assert engine.registry is container.registry
    assert engine.storage is container.storage
    assert engine.permission_manager is container.permission_manager
    assert engine.permission_manager.non_interactive is False


def test_application_loads_latest_session_when_continue_enabled(tmp_path) -> None:
    config = build_agent_config(cwd=tmp_path)
    application = MiniAgentApplication.from_config(config)
    application.container.storage.save(
        SessionRecord(id="sess_existing", cwd=str(tmp_path), messages=[user_text("上一轮")])
    )

    engine = application.create_engine(continue_session=True)

    assert engine.session_id == "sess_existing"
    assert engine.messages[0].content[0].text == "上一轮"


def test_application_diagnostics_match_cli_fields(tmp_path) -> None:
    config = build_agent_config(cwd=tmp_path, provider="fake", model="fake")
    application = MiniAgentApplication.from_config(config)

    diagnostics = application.diagnostics()

    assert diagnostics["cwd"] == str(tmp_path)
    assert diagnostics["provider"] == "fake"
    assert diagnostics["model"] == "fake"
    assert "audit.jsonl" in diagnostics["audit_path"]
