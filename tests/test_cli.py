from __future__ import annotations

from typer.testing import CliRunner

from miniagent.cli import app
from miniagent.messages import user_text
from miniagent.storage import SessionRecord, SessionStorage


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--print" in result.output
    assert "--model" in result.output


def test_cli_print(tmp_path) -> None:
    result = CliRunner().invoke(app, ["--cwd", str(tmp_path), "--print", "你好"])

    assert result.exit_code == 0
    assert "FakeModel 已收到" in result.output


def test_cli_doctor(tmp_path) -> None:
    result = CliRunner().invoke(app, ["doctor", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert "provider: fake" in result.output
    assert "audit_path" in result.output


def test_cli_context_inspect_last(tmp_path) -> None:
    storage = SessionStorage(tmp_path / ".miniagent")
    storage.save(
        SessionRecord(
            id="sess_ctx",
            cwd=str(tmp_path),
            messages=[user_text("hi")],
            state={
                "compact_summary": {"text": "历史摘要内容", "source_message_count": 2},
                "last_context": {
                    "selected_message_count": 1,
                    "total_message_count": 3,
                    "compacted_message_count": 2,
                    "budget": {"total": 8000},
                    "usage": {"history": 10},
                },
            },
        )
    )

    result = CliRunner().invoke(app, ["context", "inspect", "--cwd", str(tmp_path), "--last"])

    assert result.exit_code == 0
    assert "session_id: sess_ctx" in result.output
    assert "compacted_message_count: 2" in result.output
    assert "历史摘要内容" in result.output


def test_cli_sessions_list_and_export(tmp_path) -> None:
    storage = SessionStorage(tmp_path / ".miniagent")
    storage.save(
        SessionRecord(
            id="sess_list",
            cwd=str(tmp_path),
            messages=[user_text("hi")],
            state={"last_context": {"selected_message_count": 1}},
        )
    )

    list_result = CliRunner().invoke(app, ["sessions", "list", "--cwd", str(tmp_path)])
    export_result = CliRunner().invoke(app, ["sessions", "export", "--cwd", str(tmp_path), "--last"])

    assert list_result.exit_code == 0
    assert "sess_list" in list_result.output
    assert "messages=1" in list_result.output
    assert export_result.exit_code == 0
    assert '"snapshot"' in export_result.output
    assert '"events"' in export_result.output
    assert '"rebuilt"' in export_result.output
