from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult
from pycode_agent.utils.paths import relative_to_workspace, resolve_workspace_path


EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


class GlobInput(BaseModel):
    pattern: str
    max_results: int = Field(default=100, ge=1, le=1000)


class GlobTool(BaseTool):
    name = "glob"
    description = "按文件名模式查找工作区内的文件。"
    input_model = GlobInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = GlobInput.model_validate(input_data)
        root = resolve_workspace_path(context.cwd, ".", allow_missing=False)
        matches: list[str] = []
        for path in root.glob(args.pattern):
            if len(matches) >= args.max_results:
                break
            if not path.is_file() or _is_excluded(path, root):
                continue
            matches.append(relative_to_workspace(root, path))
        matches.sort()
        return ToolResult(display="\n".join(matches), structured_content={"matches": matches})


def _is_excluded(path: Path, root: Path) -> bool:
    rel_parts = path.resolve(strict=False).relative_to(root).parts
    return any(part in EXCLUDED_DIRS for part in rel_parts)
