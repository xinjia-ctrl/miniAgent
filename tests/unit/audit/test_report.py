from __future__ import annotations

from miniagent.audit import AuditLogger
from miniagent.audit_report import build_session_audit_report, render_audit_report
from miniagent.messages import user_text
from miniagent.storage import SessionRecord, SessionStorage


def test_audit_report_summarizes_session_failures_and_timeline(tmp_path) -> None:
    data_dir = tmp_path / ".miniagent"
    storage = SessionStorage(data_dir)
    record = SessionRecord(
        id="sess_audit",
        cwd=str(tmp_path),
        messages=[user_text("run shell")],
        tool_calls=[
            {"id": "tool_1", "name": "shell", "input": {"command": "git reset --hard"}},
        ],
        tool_results=[
            {"display": "危险 shell 命令", "is_error": True},
        ],
        permission_decisions=[
            {
                "allowed": False,
                "action": "deny",
                "reason": "危险 shell 命令",
                "risk": "dangerous",
                "source": "hard_deny",
            }
        ],
        state={
            "last_context": {
                "usage": {"system": 10, "history": 5, "tools": 2},
                "compacted_message_count": 3,
            }
        },
    )
    storage.save(record)
    audit_path = data_dir / "audit.jsonl"
    logger = AuditLogger(audit_path)
    logger.log("request_start", {"session_id": "sess_audit", "prompt": "run shell"})
    logger.log("tool_call", {"call": {"id": "tool_1", "name": "shell", "input": {}}})
    logger.log("tool_result", {"tool": "shell", "call_id": "tool_1", "is_error": True})
    logger.log("session_saved", {"session_id": "sess_audit", "done": False})

    report = build_session_audit_report(
        storage=storage,
        audit_path=audit_path,
        session_id="sess_audit",
    )
    rendered = render_audit_report(report)

    assert report.summary.tool_call_count == 1
    assert report.summary.permission_denied_count == 1
    assert report.summary.tool_error_count == 1
    assert report.summary.context_tokens == 17
    assert report.summary.compacted_message_count == 3
    assert report.summary.failed_tools[0].reason == "shell"
    assert "permission: 危险 shell 命令" in rendered
    assert "## Timeline" in rendered

    empty_timeline_report = build_session_audit_report(
        storage=storage,
        audit_path=audit_path,
        session_id="sess_audit",
        timeline_limit=0,
    )
    assert empty_timeline_report.timeline == []
