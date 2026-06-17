from __future__ import annotations

from miniagent.permissions import PermissionManager
from miniagent.config import default_config
from miniagent.engine import QueryEngine
from miniagent.messages import ToolResultBlock
from miniagent.model import FakeModelClient, tool_call_message
from miniagent.security.secrets import redact_secret_text
from miniagent.security.shell import ShellRisk, classify_shell_command
from miniagent.tool_base import ToolContext, ToolRegistry
from miniagent.tool_runner import ToolCall, ToolRunner
from miniagent.tools.read_file import ReadFileInput, ReadFileTool
from miniagent.tools.shell import ShellInput, ShellTool
from fakes import EchoTool


def test_shell_classifier_identifies_core_risks() -> None:
    assert classify_shell_command("git status").risk == ShellRisk.read_only
    assert classify_shell_command("pytest").risk == ShellRisk.test_build
    assert classify_shell_command("pip install requests").risk == ShellRisk.network
    assert classify_shell_command("git reset --hard").risk == ShellRisk.dangerous


async def test_hard_deny_blocks_dangerous_shell_even_in_bypass(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="bypass")

    decision = await manager.decide(ShellTool(), ShellInput(command="git reset --hard"), context)

    assert not decision.allowed
    assert decision.source == "hard_deny"


async def test_sensitive_path_guard_blocks_read_tool(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="default")

    decision = await manager.decide(ReadFileTool(), ReadFileInput(file_path=".env"), context)

    assert not decision.allowed
    assert decision.source == "sensitive_path_guard"


async def test_session_deny_rule_has_priority_over_allow_rule(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(
        cwd=str(workspace),
        session_id="s",
        permission_mode="default",
        state={
            "permission_rules": [
                {"action": "allow", "tool": "shell", "pattern": "python *"},
                {"action": "deny", "tool": "shell", "pattern": "python --version"},
            ]
        },
    )

    decision = await manager.decide(ShellTool(), ShellInput(command="python --version"), context)

    assert not decision.allowed
    assert decision.source == "session_rule"


async def test_session_allow_rule_can_approve_noninteractive_shell(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(
        cwd=str(workspace),
        session_id="s",
        permission_mode="default",
        state={
            "permission_rules": [
                {
                    "action": "allow",
                    "tool": "shell",
                    "pattern": "python --version",
                    "reason": "允许查询 Python 版本",
                }
            ]
        },
    )

    decision = await manager.decide(ShellTool(), ShellInput(command="python --version"), context)

    assert decision.allowed
    assert decision.reason == "允许查询 Python 版本"
    assert decision.source == "session_rule"


async def test_tool_result_is_redacted_and_marked_untrusted(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    runner = ToolRunner(registry, PermissionManager(non_interactive=True))
    context = ToolContext(cwd=str(tmp_path), session_id="s", permission_mode="default")

    results = await runner.run_calls(
        [ToolCall(id="tool_1", name="echo", input={"text": "token=abc123"})],
        context,
    )

    result = results[0].result
    assert "abc123" not in result.display
    assert result.structured_content["source"]["trust"] == "untrusted"


def test_secret_text_redaction_handles_inline_assignments() -> None:
    redacted = redact_secret_text("password=hunter2 token=abc123")

    assert "hunter2" not in redacted
    assert "abc123" not in redacted


async def test_engine_marks_tool_result_message_as_untrusted(workspace) -> None:
    model = FakeModelClient([tool_call_message("read_file", {"file_path": "README.md"}), "完成"])
    config = default_config(cwd=workspace, permission_mode="default")
    engine = QueryEngine(model_client=model, config=config)

    _ = [event async for event in engine.submit("读取 README.md")]
    tool_messages = [
        message
        for message in engine.messages
        if any(isinstance(block, ToolResultBlock) for block in message.content)
    ]

    assert "trust=untrusted" in tool_messages[0].content[0].content
