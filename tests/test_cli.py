from __future__ import annotations

import re

from typer.testing import CliRunner

from miniagent.changes import ChangeStore
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


def test_cli_changes_show_and_revert(tmp_path) -> None:
    target = tmp_path / "demo.txt"
    target.write_text("before\n", encoding="utf-8")
    change = ChangeStore(tmp_path / ".miniagent").record_change(
        session_id="sess_cli",
        tool_name="write_file",
        cwd=tmp_path,
        path=target,
        before_content="before\n",
        after_content="after\n",
        diff="--- demo.txt\n+++ demo.txt\n",
    )
    target.write_text("after\n", encoding="utf-8")

    show_result = CliRunner().invoke(app, ["changes", "show", "--cwd", str(tmp_path)])
    revert_result = CliRunner().invoke(
        app,
        ["changes", "revert", change.id, "--cwd", str(tmp_path)],
    )

    assert show_result.exit_code == 0
    assert change.id in show_result.output
    assert revert_result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "before\n"


def test_cli_memory_list_empty(tmp_path) -> None:
    result = CliRunner().invoke(app, ["memory", "list", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert "没有找到记忆" in result.output


def test_cli_memory_lifecycle(tmp_path) -> None:
    runner = CliRunner()

    remember = runner.invoke(
        app,
        [
            "memory",
            "remember",
            "默认使用中文说明",
            "--tag",
            "preference",
            "--importance",
            "5",
            "--cwd",
            str(tmp_path),
        ],
    )
    memory_id = re.search(r"mem_[0-9a-f]+", remember.output).group(0)
    listing = runner.invoke(app, ["memory", "list", "--cwd", str(tmp_path)])
    update = runner.invoke(
        app,
        [
            "memory",
            "update",
            memory_id,
            "--content",
            "默认使用中文解释",
            "--tag",
            "preference",
            "--cwd",
            str(tmp_path),
        ],
    )
    search = runner.invoke(app, ["memory", "search", "中文", "--cwd", str(tmp_path)])
    delete = runner.invoke(app, ["memory", "delete", memory_id, "--cwd", str(tmp_path)])

    assert remember.exit_code == 0
    assert listing.exit_code == 0
    assert memory_id in listing.output
    assert update.exit_code == 0
    assert search.exit_code == 0
    assert "reason=" in search.output
    assert delete.exit_code == 0
