from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from miniagent.event_log import StorageEvent
from miniagent.storage import SessionRecord, SessionStorage
from miniagent.utils.jsonl import read_jsonl


class AuditEvent(BaseModel):
    type: str
    created_at: float
    data: dict[str, Any] = Field(default_factory=dict)


class FailureStat(BaseModel):
    reason: str
    count: int


class SessionAuditSummary(BaseModel):
    session_id: str
    cwd: str
    started_at: float
    updated_at: float
    duration_ms: float
    message_count: int
    tool_call_count: int
    tool_result_count: int
    permission_count: int
    permission_denied_count: int
    tool_error_count: int
    audit_event_count: int
    storage_event_count: int
    context_tokens: int
    compacted_message_count: int
    most_used_tools: list[FailureStat] = Field(default_factory=list)
    failed_tools: list[FailureStat] = Field(default_factory=list)
    failure_reasons: list[FailureStat] = Field(default_factory=list)


class AuditTimelineItem(BaseModel):
    created_at: float
    source: str
    type: str
    detail: str


class SessionAuditReport(BaseModel):
    summary: SessionAuditSummary
    timeline: list[AuditTimelineItem] = Field(default_factory=list)
    audit_path: str
    session_path: str
    event_path: str


def build_session_audit_report(
    *,
    storage: SessionStorage,
    audit_path: str | Path,
    session_id: str,
    timeline_limit: int = 80,
) -> SessionAuditReport:
    session = storage.load(session_id)
    storage_events = storage.read_events(session_id)
    audit_events = _read_audit_events(audit_path)
    relevant_audit = _relevant_audit_events(audit_events, session)
    summary = _build_summary(
        session=session,
        audit_events=relevant_audit,
        storage_event_count=len(storage_events),
    )
    timeline = _build_timeline(
        session=session,
        audit_events=relevant_audit,
        storage_events=storage_events,
        limit=timeline_limit,
    )
    return SessionAuditReport(
        summary=summary,
        timeline=timeline,
        audit_path=str(audit_path),
        session_path=str(storage.session_path(session_id)),
        event_path=str(storage.event_path(session_id)),
    )


def render_audit_report(report: SessionAuditReport) -> str:
    summary = report.summary
    lines = [
        f"# miniAgent Audit Report: {summary.session_id}",
        "",
        "## Session Summary",
        "",
        f"- cwd: `{summary.cwd}`",
        f"- duration_ms: {summary.duration_ms:.2f}",
        f"- messages: {summary.message_count}",
        f"- tool_calls: {summary.tool_call_count}",
        f"- tool_results: {summary.tool_result_count}",
        f"- permission_decisions: {summary.permission_count}",
        f"- permission_denied: {summary.permission_denied_count}",
        f"- tool_errors: {summary.tool_error_count}",
        f"- context_tokens: {summary.context_tokens}",
        f"- compacted_messages: {summary.compacted_message_count}",
        f"- audit_events: {summary.audit_event_count}",
        f"- storage_events: {summary.storage_event_count}",
        "",
        "## Tool Usage",
        "",
    ]
    lines.extend(_stat_lines(summary.most_used_tools))
    lines.extend(["", "## Failed Tools", ""])
    lines.extend(_stat_lines(summary.failed_tools))
    lines.extend(["", "## Failure Reasons", ""])
    lines.extend(_stat_lines(summary.failure_reasons))
    lines.extend(["", "## Timeline", ""])
    if not report.timeline:
        lines.append("- <empty>")
    for item in report.timeline:
        lines.append(f"- {item.created_at:.3f} [{item.source}:{item.type}] {item.detail}")
    return "\n".join(lines) + "\n"


def _build_summary(
    *,
    session: SessionRecord,
    audit_events: list[AuditEvent],
    storage_event_count: int,
) -> SessionAuditSummary:
    tool_counter = Counter(str(call.get("name", "unknown")) for call in session.tool_calls)
    failed_tool_counter = _failed_tool_counter(session)
    permission_denied = sum(
        1 for decision in session.permission_decisions if not decision.get("allowed", False)
    )
    tool_errors = sum(1 for result in session.tool_results if result.get("is_error", False))
    last_context = session.state.get("last_context")
    usage = last_context.get("usage", {}) if isinstance(last_context, dict) else {}
    context_tokens = sum(int(value) for value in usage.values() if isinstance(value, int))
    compacted = 0
    if isinstance(last_context, dict):
        compacted = int(last_context.get("compacted_message_count") or 0)
    failures = _failure_counter(session, audit_events)
    started_at, updated_at = _observed_time_range(session, audit_events)
    duration_ms = max(0.0, (updated_at - started_at) * 1000)
    return SessionAuditSummary(
        session_id=session.id,
        cwd=session.cwd,
        started_at=started_at,
        updated_at=updated_at,
        duration_ms=round(duration_ms, 2),
        message_count=len(session.messages),
        tool_call_count=len(session.tool_calls),
        tool_result_count=len(session.tool_results),
        permission_count=len(session.permission_decisions),
        permission_denied_count=permission_denied,
        tool_error_count=tool_errors,
        audit_event_count=len(audit_events),
        storage_event_count=storage_event_count,
        context_tokens=context_tokens,
        compacted_message_count=compacted,
        most_used_tools=_counter_stats(tool_counter),
        failed_tools=_counter_stats(failed_tool_counter),
        failure_reasons=_counter_stats(failures),
    )


def _build_timeline(
    *,
    session: SessionRecord,
    audit_events: list[AuditEvent],
    storage_events: list[StorageEvent],
    limit: int,
) -> list[AuditTimelineItem]:
    if limit <= 0:
        return []

    items: list[AuditTimelineItem] = []
    for event in audit_events:
        items.append(
            AuditTimelineItem(
                created_at=event.created_at,
                source="audit",
                type=event.type,
                detail=_audit_detail(event),
            )
        )
    for event in storage_events:
        if event.type in {"message_appended", "state_snapshot"}:
            continue
        items.append(
            AuditTimelineItem(
                created_at=event.created_at,
                source="storage",
                type=event.type,
                detail=_storage_detail(event.data),
            )
        )
    items.sort(key=lambda item: item.created_at)
    return items[-limit:]


def _read_audit_events(path: str | Path) -> list[AuditEvent]:
    return [AuditEvent.model_validate(row) for row in read_jsonl(path)]


def _relevant_audit_events(
    events: list[AuditEvent],
    session: SessionRecord,
) -> list[AuditEvent]:
    call_ids = {str(call.get("id")) for call in session.tool_calls if call.get("id")}
    relevant: list[AuditEvent] = []
    for event in events:
        data = event.data
        if data.get("session_id") == session.id:
            relevant.append(event)
            continue
        call = data.get("call")
        if isinstance(call, dict) and str(call.get("id")) in call_ids:
            relevant.append(event)
            continue
        if str(data.get("call_id")) in call_ids:
            relevant.append(event)
    return relevant


def _failure_counter(session: SessionRecord, audit_events: list[AuditEvent]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for decision in session.permission_decisions:
        if not decision.get("allowed", False):
            counter[f"permission: {decision.get('reason', 'unknown')}"] += 1
    for result in session.tool_results:
        if result.get("is_error", False):
            counter[f"tool_error: {_first_line(result.get('display', 'unknown'))}"] += 1
    for event in audit_events:
        if event.type == "error":
            counter[f"engine: {_first_line(event.data.get('message', 'unknown'))}"] += 1
    return counter


def _failed_tool_counter(session: SessionRecord) -> Counter[str]:
    counter: Counter[str] = Counter()
    for call, result in zip(session.tool_calls, session.tool_results, strict=False):
        if result.get("is_error", False):
            counter[str(call.get("name", "unknown"))] += 1
    return counter


def _counter_stats(counter: Counter[str]) -> list[FailureStat]:
    return [
        FailureStat(reason=reason, count=count)
        for reason, count in counter.most_common()
    ]


def _stat_lines(stats: list[FailureStat]) -> list[str]:
    if not stats:
        return ["- <none>"]
    return [f"- {stat.reason}: {stat.count}" for stat in stats]


def _audit_detail(event: AuditEvent) -> str:
    data = event.data
    if event.type == "request_start":
        return _first_line(data.get("prompt", ""))
    if event.type == "session_saved":
        return f"done={data.get('done', 'unknown')}"
    if event.type in {"tool_start", "tool_call"}:
        call = data.get("call", {})
        if isinstance(call, dict):
            return f"{call.get('name', 'unknown')} {call.get('id', '')}".strip()
    if event.type == "permission_decision":
        return f"{data.get('tool', 'unknown')} {data.get('decision', {})}"
    if event.type == "tool_result":
        return f"{data.get('tool', 'unknown')} error={data.get('is_error', False)}"
    if event.type == "file_change":
        return f"{data.get('tool', 'unknown')} change_id={data.get('change_id')}"
    if event.type == "model_request":
        return f"turn={data.get('turn')} messages={data.get('message_count')}"
    if event.type == "error":
        return _first_line(data.get("message", "unknown"))
    return _storage_detail(data)


def _observed_time_range(
    session: SessionRecord,
    audit_events: list[AuditEvent],
) -> tuple[float, float]:
    if audit_events:
        ordered = sorted(audit_events, key=lambda event: event.created_at)
        return ordered[0].created_at, ordered[-1].created_at
    return session.created_at, session.updated_at


def _storage_detail(data: dict[str, Any]) -> str:
    if "index" in data:
        return f"index={data['index']}"
    if "json_path" in data:
        return str(data["json_path"])
    return ""


def _first_line(value: object) -> str:
    text = str(value or "")
    return text.splitlines()[0][:180] if text else "unknown"
