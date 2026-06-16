from __future__ import annotations

from pydantic import BaseModel, Field

from miniagent.tool_base import BaseTool, ToolContext, ToolResult
from miniagent.utils.paths import resolve_workspace_path
from miniagent.utils.text import clip_text, format_with_line_numbers, read_text


class ReadFileInput(BaseModel):
    file_path: str
    offset: int | None = Field(default=None, ge=1)
    limit: int | None = Field(default=None, ge=1)


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "读取工作区内的文本文件，并返回带行号的内容。"
    input_model = ReadFileInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = ReadFileInput.model_validate(input_data)
        path = resolve_workspace_path(context.cwd, args.file_path)
        content = read_text(path)
        lines = content.splitlines()
        start = args.offset or 1
        end = start - 1 + args.limit if args.limit else len(lines)
        selected = "\n".join(lines[start - 1 : end])
        display = format_with_line_numbers(selected, start_line=start)

        if args.offset is None and args.limit is None:
            stat = path.stat()
            context.file_reads[str(path)] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}

        return ToolResult(
            display=clip_text(display, context.max_result_chars),
            structured_content={"path": str(path), "line_count": len(lines)},
        )
