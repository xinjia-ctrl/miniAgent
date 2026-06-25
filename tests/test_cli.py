from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from miniagent.audit import AuditLogger
from miniagent.changes import ChangeStore
from miniagent.cli import app
from miniagent.messages import user_text
from miniagent.storage import SessionRecord, SessionStorage


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_cli_print(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["--cwd", str(tmp_path), "--model", "fake", "--print", "你好"],
    )

    assert result.exit_code == 0
    assert "FakeModel 已收到" in result.output


def test_cli_doctor(tmp_path) -> None:
    result = CliRunner().invoke(app, ["doctor", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert "provider: fake" in result.output
    assert "audit_path" in result.output


def test_cli_config_set_show_and_reset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    runner = CliRunner()

    configured = runner.invoke(
        app,
        [
            "config",
            "set",
            "--provider",
            "openai-compatible",
            "--model",
            "deepseek-v4-flash",
            "--base-url",
            "https://api.deepseek.com/chat/completions",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--permission-mode",
            "accept_edits",
        ],
    )
    shown = runner.invoke(app, ["config", "show", "--cwd", str(tmp_path)])
    reset = runner.invoke(app, ["config", "reset"])

    assert configured.exit_code == 0
    assert "已保存用户配置" in configured.output
    assert shown.exit_code == 0
    assert "provider: openai-compatible" in shown.output
    assert "model: deepseek-v4-flash" in shown.output
    assert "api_key_env: OPENAI_API_KEY" in shown.output
    assert "api_key_configured: false" in shown.output
    assert reset.exit_code == 0
    assert "已删除用户配置" in reset.output


def test_cli_doctor_uses_saved_user_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))
    runner = CliRunner()
    configured = runner.invoke(
        app,
        [
            "config",
            "set",
            "--provider",
            "openai-compatible",
            "--model",
            "deepseek-v4-flash",
            "--base-url",
            "https://api.deepseek.com/chat/completions",
        ],
    )

    result = runner.invoke(app, ["doctor", "--cwd", str(tmp_path)])

    assert configured.exit_code == 0
    assert result.exit_code == 0
    assert "provider: openai-compatible" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "base_url: https://api.deepseek.com/chat/completions" in result.output


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


def test_cli_audit_show(tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    storage = SessionStorage(data_dir)
    storage.save(
        SessionRecord(
            id="sess_audit_cli",
            cwd=str(tmp_path),
            messages=[user_text("hi")],
            tool_calls=[{"id": "tool_1", "name": "read_file", "input": {"file_path": "README.md"}}],
            tool_results=[{"display": "ok", "is_error": False}],
            permission_decisions=[{"allowed": True, "action": "allow", "reason": "只读"}],
            state={"last_context": {"usage": {"system": 1, "history": 2}}},
        )
    )
    logger = AuditLogger(data_dir / "audit.jsonl")
    logger.log("request_start", {"session_id": "sess_audit_cli", "prompt": "hi"})
    logger.log("tool_call", {"call": {"id": "tool_1", "name": "read_file"}})
    logger.log("session_saved", {"session_id": "sess_audit_cli"})

    result = CliRunner().invoke(
        app,
        ["audit", "show", "sess_audit_cli", "--cwd", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "miniAgent Audit Report" in result.output
    assert "tool_calls: 1" in result.output
    assert "read_file" in result.output


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


def test_cli_tools_list_and_inspect(tmp_path) -> None:
    list_result = CliRunner().invoke(app, ["tools", "list", "--cwd", str(tmp_path)])
    inspect_result = CliRunner().invoke(app, ["tools", "inspect", "read_file", "--cwd", str(tmp_path)])

    assert list_result.exit_code == 0
    assert "read_file" in list_result.output
    assert "source=builtin" in list_result.output
    assert inspect_result.exit_code == 0
    assert '"name": "read_file"' in inspect_result.output


def test_cli_plugins_list_empty(tmp_path) -> None:
    result = CliRunner().invoke(app, ["plugins", "list", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert "没有找到插件" in result.output


def test_cli_plugins_install(tmp_path) -> None:
    source = tmp_path / "sample-plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "name": "sample-plugin",
                "version": "0.1.0",
                "description": "Sample plugin",
                "entry": "plugin.py",
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source / "plugin.py").write_text(
        "def register(registry):\n    return None\n",
        encoding="utf-8",
    )

    install = CliRunner().invoke(app, ["plugins", "install", str(source), "--cwd", str(tmp_path)])
    listing = CliRunner().invoke(app, ["plugins", "list", "--cwd", str(tmp_path)])

    assert install.exit_code == 0
    assert "已安装插件：sample-plugin" in install.output
    assert listing.exit_code == 0
    assert "sample-plugin" in listing.output
