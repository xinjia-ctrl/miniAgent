from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult
from pycode_agent.tools.glob import EXCLUDED_DIRS
from pycode_agent.utils.paths import relative_to_workspace, resolve_workspace_path
from pycode_agent.utils.text import clip_text, is_probably_binary_file


class GrepInput(BaseModel):
    pattern: str
    path: str = "."
    case_sensitive: bool = True
    max_results: int = Field(default=100, ge=1, le=1000)


class GrepTool(BaseTool):
    name = "grep"
    description = "在工作区文本文件中搜索内容。"
    input_model = GrepInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = GrepInput.model_validate(input_data)
        base = resolve_workspace_path(context.cwd, args.path)
        root = Path(context.cwd).resolve(strict=False)
        regex = re.compile(args.pattern, 0 if args.case_sensitive else re.IGNORECASE)
        files = [base] if base.is_file() else [path for path in base.rglob("*") if path.is_file()]
        results: list[str] = []
        for path in files:
            if len(results) >= args.max_results:
                break
            if _is_excluded(path, root) or is_probably_binary_file(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for index, line in enumerate(lines, start=1):
                if regex.search(line):
                    results.append(f"{relative_to_workspace(root, path)}:{index}: {line}")
                    if len(results) >= args.max_results:
                        break
        display = clip_text("\n".join(results), context.max_result_chars)
        return ToolResult(display=display, structured_content={"matches": results})


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve(strict=False).relative_to(root).parts
    except ValueError:
        return True
    return any(part in EXCLUDED_DIRS for part in parts)
