from __future__ import annotations

from pydantic import BaseModel, Field


class EvalMetrics(BaseModel):
    completed: bool = False
    tool_calls: int = 0
    permission_denials: int = 0
    unsafe_attempts: int = 0
    errors: int = 0
    context_tokens: int = 0
    latency_ms: float = 0
    edit_accuracy: bool = True
    recovery_score: float | None = None
    audit_complete: bool = False


class EvalCaseResult(BaseModel):
    id: str
    description: str = ""
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    metrics: EvalMetrics


class EvalSummary(BaseModel):
    total_cases: int
    passed: int
    failed: int
    success_rate: float
    avg_tool_calls: float
    permission_denied_count: int
    unsafe_attempt_count: int
    avg_context_tokens: float
    avg_latency_ms: float
    edit_accuracy_rate: float
    recovery_score: float | None = None
    audit_completeness_rate: float


def summarize_results(results: list[EvalCaseResult]) -> EvalSummary:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    recovery_values = [
        result.metrics.recovery_score
        for result in results
        if result.metrics.recovery_score is not None
    ]
    return EvalSummary(
        total_cases=total,
        passed=passed,
        failed=total - passed,
        success_rate=_rate(passed, total),
        avg_tool_calls=_avg(result.metrics.tool_calls for result in results),
        permission_denied_count=sum(result.metrics.permission_denials for result in results),
        unsafe_attempt_count=sum(result.metrics.unsafe_attempts for result in results),
        avg_context_tokens=_avg(result.metrics.context_tokens for result in results),
        avg_latency_ms=_avg(result.metrics.latency_ms for result in results),
        edit_accuracy_rate=_rate(
            sum(1 for result in results if result.metrics.edit_accuracy),
            total,
        ),
        recovery_score=_avg(recovery_values) if recovery_values else None,
        audit_completeness_rate=_rate(
            sum(1 for result in results if result.metrics.audit_complete),
            total,
        ),
    )


def _avg(values) -> float:
    items = [float(value) for value in values]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 2)


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total, 4)
