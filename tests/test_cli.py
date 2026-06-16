from __future__ import annotations

from typer.testing import CliRunner

from pycode_agent.cli import app


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
