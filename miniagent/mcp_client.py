from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from miniagent.utils.text import clip_text


class StdioMcpServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=5, gt=0, le=60)
    max_output_chars: int = Field(default=6000, ge=100, le=50000)


class McpToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    read_only: bool = False


class StdioMcpClient:
    """极简 stdio MCP 客户端：每次请求启动一次本地进程并交换一条 JSON-RPC 消息。"""

    def __init__(self, config: StdioMcpServerConfig, *, cwd: str | Path):
        self.config = config
        self.cwd = Path(cwd)
        self._next_id = 1

    def list_tools(self) -> list[McpToolSpec]:
        result = self.request("tools/list")
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [self._tool_spec(raw_tool) for raw_tool in tools if isinstance(raw_tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict):
            return result
        return {"content": [{"type": "text", "text": str(result)}]}

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        try:
            completed = subprocess.run(
                [self.config.command, *self.config.args],
                input=json.dumps(request, ensure_ascii=False) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.cwd,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"MCP 请求超时：{method}") from exc
        if completed.returncode != 0 and not completed.stdout.strip():
            stderr = clip_text(completed.stderr.strip(), self.config.max_output_chars)
            raise RuntimeError(f"MCP server 退出码 {completed.returncode}: {stderr}")

        response = self._parse_response(completed.stdout)
        if response.get("id") not in (request_id, None):
            raise RuntimeError("MCP 响应 id 不匹配")
        if response.get("error"):
            raise RuntimeError(f"MCP 错误：{response['error']}")
        result = response.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def _parse_response(self, stdout: str) -> dict[str, Any]:
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                response = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict):
                return response
        clipped = clip_text(stdout.strip(), self.config.max_output_chars)
        raise RuntimeError(f"MCP 响应不是 JSON：{clipped}")

    @staticmethod
    def _tool_spec(raw_tool: dict[str, Any]) -> McpToolSpec:
        annotations = raw_tool.get("annotations") or {}
        return McpToolSpec(
            name=str(raw_tool["name"]),
            description=str(raw_tool.get("description") or ""),
            input_schema=dict(
                raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {"type": "object"}
            ),
            read_only=bool(raw_tool.get("readOnly") or annotations.get("readOnlyHint")),
        )


def format_mcp_result(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content = result.get("content")
    if isinstance(content, list):
        lines: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                lines.append(str(block.get("text", "")))
            else:
                lines.append(json.dumps(block, ensure_ascii=False))
        display = "\n".join(line for line in lines if line)
    else:
        display = json.dumps(result, ensure_ascii=False, indent=2)
    structured = {
        "mcp": result,
        "structuredContent": result.get("structuredContent") or result.get("structured_content"),
    }
    return display, structured
