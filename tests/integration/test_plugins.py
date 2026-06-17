from __future__ import annotations

import json
import sys

from miniagent.app import MiniAgentApplication
from miniagent.bootstrap import build_agent_config
from miniagent.tool_base import ToolContext
from miniagent.tool_runner import ToolCall, ToolRunner


def _write_python_plugin(root) -> None:
    plugin_dir = root / ".miniagent" / "plugins" / "demo-python"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-python",
                "version": "0.1.0",
                "description": "Demo python plugin",
                "entry": "plugin.py",
                "tools": ["plugin_echo"],
                "permissions": ["read-only"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """
from pydantic import BaseModel

from miniagent.tool_base import BaseTool, ToolContext, ToolResult


class PluginEchoInput(BaseModel):
    text: str


class PluginEchoTool(BaseTool):
    name = "plugin_echo"
    description = "Echo from plugin."
    input_model = PluginEchoInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = PluginEchoInput.model_validate(input_data)
        return ToolResult(display=f"plugin:{args.text}")


def register(registry):
    registry.register(PluginEchoTool())
""".lstrip(),
        encoding="utf-8",
    )


def _write_mcp_plugin(root) -> None:
    plugin_dir = root / ".miniagent" / "plugins" / "demo-mcp"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-mcp",
                "version": "0.1.0",
                "description": "Demo MCP plugin",
                "tools": ["mcp_echo"],
                "mcp": {
                    "command": sys.executable,
                    "args": ["server.py"],
                    "timeout_seconds": 5,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "server.py").write_text(
        """
import json
import sys


request = json.loads(sys.stdin.readline())
method = request.get("method")
if method == "tools/list":
    result = {
        "tools": [
            {
                "name": "mcp_echo",
                "description": "Echo from MCP.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                "annotations": {"readOnlyHint": True},
            }
        ]
    }
elif method == "tools/call":
    text = request.get("params", {}).get("arguments", {}).get("text", "")
    result = {
        "content": [{"type": "text", "text": f"mcp:{text}"}],
        "structuredContent": {"echo": text},
    }
else:
    result = {}
print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}))
""".lstrip(),
        encoding="utf-8",
    )


async def test_python_plugin_loads_and_runs_through_tool_runner(tmp_path) -> None:
    _write_python_plugin(tmp_path)
    application = MiniAgentApplication.from_config(build_agent_config(cwd=tmp_path))

    tool = application.inspect_tool("plugin_echo")
    runner = ToolRunner(
        application.container.registry,
        application.container.permission_manager,
        application.container.audit_logger,
    )
    context = ToolContext(
        cwd=str(tmp_path),
        session_id="sess_plugin",
        permission_mode="default",
        data_dir=str(tmp_path / ".miniagent"),
    )
    results = await runner.run_calls(
        [ToolCall(id="tool_1", name="plugin_echo", input={"text": "hi"})],
        context,
    )

    assert tool["metadata"]["plugin"] == "demo-python"
    assert results[0].permission.allowed
    assert results[0].result.display == "plugin:hi"
    assert "plugin_echo" in (tmp_path / ".miniagent" / "audit.jsonl").read_text(encoding="utf-8")


async def test_mcp_plugin_loads_external_tool_adapter(tmp_path) -> None:
    _write_mcp_plugin(tmp_path)
    application = MiniAgentApplication.from_config(build_agent_config(cwd=tmp_path))
    runner = ToolRunner(
        application.container.registry,
        application.container.permission_manager,
        application.container.audit_logger,
    )
    context = ToolContext(
        cwd=str(tmp_path),
        session_id="sess_mcp",
        permission_mode="default",
        data_dir=str(tmp_path / ".miniagent"),
    )

    results = await runner.run_calls(
        [ToolCall(id="tool_1", name="mcp_echo", input={"text": "hello"})],
        context,
    )

    assert application.inspect_tool("mcp_echo")["metadata"]["kind"] == "mcp"
    assert results[0].permission.allowed
    assert results[0].result.display == "mcp:hello"
    assert results[0].result.structured_content["mcp"]["structuredContent"]["echo"] == "hello"
