from __future__ import annotations

from miniagent.changes import ChangeStore
from miniagent.audit import AuditLogger
from miniagent.permissions import PermissionManager
from miniagent.tool_base import ToolContext, ToolRegistry
from miniagent.tool_runner import ToolCall, ToolRunner
from miniagent.tools.edit_file import EditFileInput, EditFileTool
from miniagent.tools.read_file import ReadFileInput, ReadFileTool
from miniagent.tools.write_file import WriteFileInput, WriteFileTool


async def test_write_file_creates_checkpoint_and_revert_restores_file(workspace, tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    context = ToolContext(
        cwd=str(workspace),
        session_id="sess_changes",
        permission_mode="accept_edits",
        data_dir=str(data_dir),
    )
    original = (workspace / "README.md").read_text(encoding="utf-8")
    await ReadFileTool().call(ReadFileInput(file_path="README.md"), context)

    result = await WriteFileTool().call(
        WriteFileInput(file_path="README.md", content="# Demo\nchanged\n"),
        context,
    )
    change_id = result.structured_content["change_id"]
    revert = ChangeStore(data_dir).revert(change_id, cwd=workspace)

    assert revert.restored
    assert (workspace / "README.md").read_text(encoding="utf-8") == original


async def test_write_file_checkpoint_revert_deletes_new_file(workspace, tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    context = ToolContext(
        cwd=str(workspace),
        session_id="sess_changes",
        permission_mode="accept_edits",
        data_dir=str(data_dir),
    )

    result = await WriteFileTool().call(
        WriteFileInput(file_path="new.txt", content="hello\n"),
        context,
    )
    change_id = result.structured_content["change_id"]
    ChangeStore(data_dir).revert(change_id, cwd=workspace)

    target = workspace / "new.txt"
    assert not target.exists() or target.read_text(encoding="utf-8") == ""


async def test_edit_file_creates_checkpoint(workspace, tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    context = ToolContext(
        cwd=str(workspace),
        session_id="sess_changes",
        permission_mode="accept_edits",
        data_dir=str(data_dir),
    )
    await ReadFileTool().call(ReadFileInput(file_path="README.md"), context)

    result = await EditFileTool().call(
        EditFileInput(file_path="README.md", old_string="hello agent", new_string="hello runtime"),
        context,
    )

    change = ChangeStore(data_dir).get(result.structured_content["change_id"])
    assert change.tool_name == "edit_file"
    assert "---" in change.diff


async def test_tool_runner_rolls_back_prior_file_change_when_later_edit_fails(workspace, tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    (workspace / "a.txt").write_text("old a\n", encoding="utf-8")
    (workspace / "b.txt").write_text("old b\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    context = ToolContext(
        cwd=str(workspace),
        session_id="sess_changes",
        permission_mode="accept_edits",
        data_dir=str(data_dir),
        file_reads={
            str(workspace / "a.txt"): _read_record(workspace / "a.txt"),
            str(workspace / "b.txt"): _read_record(workspace / "b.txt"),
        },
    )
    runner = ToolRunner(registry, PermissionManager(non_interactive=True))

    results = await runner.run_calls(
        [
            ToolCall(id="tool_1", name="write_file", input={"file_path": "a.txt", "content": "new a\n"}),
            ToolCall(
                id="tool_2",
                name="edit_file",
                input={"file_path": "b.txt", "old_string": "missing", "new_string": "new b"},
            ),
        ],
        context,
    )

    assert results[-1].result.is_error
    assert "[rollback]" in results[-1].result.display
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "old a\n"


async def test_tool_runner_audits_file_change_diff(workspace, tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    context = ToolContext(
        cwd=str(workspace),
        session_id="sess_changes",
        permission_mode="accept_edits",
        data_dir=str(data_dir),
    )
    runner = ToolRunner(
        registry,
        PermissionManager(non_interactive=True),
        AuditLogger(tmp_path / "audit.jsonl"),
    )

    await runner.run_calls(
        [ToolCall(id="tool_1", name="write_file", input={"file_path": "new.txt", "content": "hello\n"})],
        context,
    )

    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "file_change" in audit
    assert "change_id" in audit
    assert "+hello" in audit


def _read_record(path):
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
