from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from miniagent.mcp_client import (
    McpToolSpec,
    StdioMcpClient,
    StdioMcpServerConfig,
    format_mcp_result,
)
from miniagent.tool_base import BaseTool, ToolContext, ToolRegistry, ToolResult


PLUGIN_MANIFEST = "plugin.json"


class PluginManifest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    entry: str | None = None
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcp: StdioMcpServerConfig | None = None

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("插件 version 不能为空")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
        if not value or any(character not in allowed for character in value):
            raise ValueError("插件 name 只能包含字母、数字、下划线、点和横线")
        return value

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.strip():
                raise ValueError("插件 permissions 不能包含空声明")
        return value

    @model_validator(mode="after")
    def _validate_entry_or_mcp(self) -> PluginManifest:
        if not self.entry and self.mcp is None:
            raise ValueError("插件必须提供 entry 或 mcp 配置")
        return self


class PluginStatus(BaseModel):
    name: str
    version: str = ""
    description: str = ""
    path: str
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    loaded: bool = False
    error: str | None = None


class ExternalToolInput(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExternalMcpTool(BaseTool):
    input_model = ExternalToolInput

    def __init__(
        self,
        *,
        plugin_name: str,
        spec: McpToolSpec,
        client: StdioMcpClient,
    ):
        self.plugin_name = plugin_name
        self.remote_name = spec.name
        self.name = spec.name
        self.description = spec.description or f"MCP tool from plugin {plugin_name}"
        self.input_schema = spec.input_schema
        self.read_only = spec.read_only
        self.client = client

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def validate_input(self, input_data: dict[str, Any] | BaseModel) -> ExternalToolInput:
        if isinstance(input_data, ExternalToolInput):
            return input_data
        if isinstance(input_data, BaseModel):
            return ExternalToolInput(arguments=input_data.model_dump(mode="json"))
        return ExternalToolInput(arguments=dict(input_data))

    def is_read_only(self, input_data: BaseModel) -> bool:
        return self.read_only

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return self.read_only

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = ExternalToolInput.model_validate(input_data)
        result = await asyncio.to_thread(self.client.call_tool, self.remote_name, args.arguments)
        display, structured = format_mcp_result(result)
        return ToolResult(display=display, structured_content=structured)


def plugin_roots(*, data_dir: str | Path, cwd: str | Path) -> list[Path]:
    roots = [Path(data_dir) / "plugins", Path(cwd) / ".miniAgent" / "plugins"]
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return unique


def discover_plugins(*, data_dir: str | Path, cwd: str | Path) -> list[PluginStatus]:
    statuses: list[PluginStatus] = []
    for root in plugin_roots(data_dir=data_dir, cwd=cwd):
        if not root.exists():
            continue
        for path in sorted(item for item in root.iterdir() if item.is_dir()):
            statuses.append(_status_from_manifest(path))
    return statuses


def load_plugins(registry: ToolRegistry, *, data_dir: str | Path, cwd: str | Path) -> list[PluginStatus]:
    statuses: list[PluginStatus] = []
    for status in discover_plugins(data_dir=data_dir, cwd=cwd):
        plugin_dir = Path(status.path)
        statuses.append(load_plugin(registry, plugin_dir))
    return statuses


def load_plugin(registry: ToolRegistry, plugin_dir: str | Path) -> PluginStatus:
    plugin_path = Path(plugin_dir)
    registered: list[str] = []
    before = set(registry.names())
    try:
        manifest = read_manifest(plugin_path)
        if manifest.entry:
            _load_python_entry(registry, plugin_path, manifest)
        if manifest.mcp:
            _load_mcp_tools(registry, plugin_path, manifest)

        registered = sorted(set(registry.names()) - before)
        _validate_declared_tools(manifest, registered)
        for tool_name in registered:
            registry.set_metadata(tool_name, _tool_metadata(manifest, plugin_path, tool_name))
        return PluginStatus(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            path=str(plugin_path),
            tools=registered,
            permissions=manifest.permissions,
            loaded=True,
        )
    except Exception as exc:
        registered = sorted(set(registry.names()) - before)
        for tool_name in registered:
            registry.unregister(tool_name)
        fallback = _status_from_manifest(plugin_path)
        fallback.loaded = False
        fallback.error = str(exc)
        return fallback


def read_manifest(plugin_dir: str | Path) -> PluginManifest:
    manifest_path = Path(plugin_dir) / PLUGIN_MANIFEST
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return PluginManifest.model_validate(raw)


def install_plugin(
    source: str | Path,
    *,
    data_dir: str | Path,
    cwd: str | Path,
    force: bool = False,
) -> PluginStatus:
    source_path = Path(source).resolve()
    manifest = read_manifest(source_path)
    target_root = plugin_roots(data_dir=data_dir, cwd=cwd)[0]
    target = target_root / manifest.name
    if target.exists():
        if not force:
            raise FileExistsError(f"插件已存在：{manifest.name}")
        shutil.rmtree(target)
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_path, target)
    return _status_from_manifest(target)


def _status_from_manifest(plugin_dir: Path) -> PluginStatus:
    try:
        manifest = read_manifest(plugin_dir)
        return PluginStatus(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            path=str(plugin_dir),
            tools=manifest.tools,
            permissions=manifest.permissions,
        )
    except Exception as exc:
        return PluginStatus(
            name=plugin_dir.name,
            path=str(plugin_dir),
            loaded=False,
            error=str(exc),
        )


def _load_python_entry(registry: ToolRegistry, plugin_dir: Path, manifest: PluginManifest) -> None:
    entry = _safe_child(plugin_dir, manifest.entry or "")
    module = _import_entry_module(entry, manifest.name)
    if hasattr(module, "register"):
        module.register(registry)
        return
    if hasattr(module, "tools"):
        for tool in module.tools():
            if not isinstance(tool, BaseTool):
                raise TypeError("plugin tools() 必须返回 BaseTool 实例")
            registry.register(tool)
        return
    raise ValueError("plugin entry 必须提供 register(registry) 或 tools()")


def _load_mcp_tools(registry: ToolRegistry, plugin_dir: Path, manifest: PluginManifest) -> None:
    if manifest.mcp is None:
        return
    client = StdioMcpClient(manifest.mcp, cwd=plugin_dir)
    for spec in client.list_tools():
        registry.register(
            ExternalMcpTool(plugin_name=manifest.name, spec=spec, client=client),
            metadata=_tool_metadata(manifest, plugin_dir, spec.name),
        )


def _import_entry_module(entry: Path, plugin_name: str) -> ModuleType:
    module_name = f"miniagent_plugin_{plugin_name.replace('-', '_')}_{abs(hash(entry))}"
    spec = importlib.util.spec_from_file_location(module_name, entry)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件入口：{entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(entry.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(entry.parent))
    return module


def _safe_child(root: Path, child: str) -> Path:
    root_resolved = root.resolve(strict=False)
    target = (root / child).resolve(strict=False)
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("插件入口不能逃逸插件目录") from exc
    return target


def _validate_declared_tools(manifest: PluginManifest, registered: list[str]) -> None:
    if not manifest.tools:
        return
    missing = sorted(set(manifest.tools) - set(registered))
    if missing:
        raise ValueError(f"插件声明了未注册工具：{', '.join(missing)}")


def _tool_metadata(manifest: PluginManifest, plugin_dir: Path, tool_name: str) -> dict[str, Any]:
    return {
        "source": "plugin",
        "plugin": manifest.name,
        "plugin_version": manifest.version,
        "plugin_path": str(plugin_dir),
        "declared_permissions": manifest.permissions,
        "tool": tool_name,
        "kind": "mcp" if manifest.mcp else "python",
    }
