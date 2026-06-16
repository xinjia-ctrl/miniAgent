from __future__ import annotations

from pydantic import BaseModel

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult
from pycode_agent.tools.write_file import _ensure_fresh_read
from pycode_agent.utils.diff import unified_diff
from pycode_agent.utils.paths import resolve_workspace_path


class EditFileInput(BaseModel):
    file_path: str
    old_string: str
    new_string: str
    replace_all: bool = False


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "对工作区内文本文件执行精确字符串替换。"
    input_model = EditFileInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = EditFileInput.model_validate(input_data)
        path = resolve_workspace_path(context.cwd, args.file_path)
        _ensure_fresh_read(path, context)
        old = path.read_text(encoding="utf-8")
        count = old.count(args.old_string)
        if count == 0:
            return ToolResult(display="old_string 在文件中没有匹配项", is_error=True)
        if count > 1 and not args.replace_all:
            return ToolResult(
                display=f"old_string 在文件中出现 {count} 次。请提供更多上下文，或设置 replace_all=true。",
                is_error=True,
            )
        new = old.replace(args.old_string, args.new_string, -1 if args.replace_all else 1)
        diff = unified_diff(old, new, fromfile=str(path), tofile=str(path))
        path.write_text(new, encoding="utf-8")
        stat = path.stat()
        context.file_reads[str(path)] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
        return ToolResult(display=diff, structured_content={"path": str(path), "replacements": count})
