from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.metrics import EvalCaseResult, EvalMetrics, EvalSummary, summarize_results
from miniagent.config import default_config
from miniagent.engine import QueryEngine
from miniagent.events import (
    DONE,
    ERROR,
    PERMISSION_DECISION,
    SESSION_SAVED,
    TOOL_ERROR,
    TOOL_RESULT,
    TOOL_START,
)
from miniagent.model import FakeModelClient, tool_call_message


DEFAULT_CASES_DIR = ROOT / "evals" / "cases"
DEFAULT_OUTPUT_DIR = ROOT / ".miniagent" / "evals"
DEFAULT_WORKSPACE_ROOT = ROOT / ".miniagent" / "eval_workspaces"


class EvalFileExpectation(BaseModel):
    exists: bool = True
    contains: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)
    equals: str | None = None


class EvalSafetyExpectation(BaseModel):
    must_not_touch: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    prompt: str
    permission_mode: str = "default"
    context_token_budget: int | None = None
    max_turns: int | None = None
    workspace_files: dict[str, str] = Field(default_factory=dict)
    fake_script: list[Any] = Field(default_factory=list)
    expected_files: dict[str, EvalFileExpectation] = Field(default_factory=dict)
    expected_file_modified: str | None = None
    max_tool_calls: int | None = None
    forbidden_tools: list[str] = Field(default_factory=list)
    expect_permission_denials_min: int = 0
    expect_unsafe_attempts_min: int = 0
    max_errors: int = 0
    recovery_expected: bool = False
    safety: EvalSafetyExpectation = Field(default_factory=EvalSafetyExpectation)

    @model_validator(mode="after")
    def _legacy_expected_file(self) -> EvalCase:
        if self.expected_file_modified and self.expected_file_modified not in self.expected_files:
            self.expected_files[self.expected_file_modified] = EvalFileExpectation()
        return self


class EvalRunResult(BaseModel):
    run_id: str
    model: str
    created_at: float
    cases_dir: str
    results: list[EvalCaseResult]
    summary: EvalSummary


class EvalCompareResult(BaseModel):
    baseline: str
    current: str
    success_rate_delta: float
    passed_delta: int
    unsafe_attempt_delta: int
    avg_tool_calls_delta: float
    avg_latency_ms_delta: float
    regression_cases: list[str] = Field(default_factory=list)
    improved_cases: list[str] = Field(default_factory=list)


async def run_eval_suite(
    *,
    model: str = "fake",
    case_id: str | None = None,
    cases_dir: str | Path = DEFAULT_CASES_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    run_id: str | None = None,
) -> EvalRunResult:
    if model != "fake":
        raise ValueError("阶段 26 的 deterministic eval 仅支持 --model fake")
    case_paths = _case_paths(Path(cases_dir), case_id=case_id)
    if not case_paths:
        raise FileNotFoundError("没有找到评测用例")

    actual_run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    results = [
        await run_case(path, model=model, run_id=actual_run_id)
        for path in case_paths
    ]
    run = EvalRunResult(
        run_id=actual_run_id,
        model=model,
        created_at=time.time(),
        cases_dir=str(Path(cases_dir)),
        results=results,
        summary=summarize_results(results),
    )
    write_reports(run, output_dir=output_dir)
    return run


async def run_case(path: Path, *, model: str = "fake", run_id: str = "manual") -> EvalCaseResult:
    case = load_case(path)
    workspace = _prepare_workspace(path, case, run_id=run_id)
    before_safety = _snapshot_safety_files(workspace, case)
    config = default_config(
        cwd=workspace,
        permission_mode=case.permission_mode,
        non_interactive=True,
    )
    if case.context_token_budget is not None:
        config.context_token_budget = case.context_token_budget
    if case.max_turns is not None:
        config.max_turns = case.max_turns

    model_client = FakeModelClient(_build_fake_script(case))
    engine = QueryEngine(config=config, model_client=model_client)
    started = time.perf_counter()

    completed = False
    tool_calls = 0
    permission_denials = 0
    unsafe_attempts = 0
    errors = 0
    called_tools: list[str] = []
    saved_session = False

    async for event in engine.submit(case.prompt):
        if event.type == DONE:
            completed = True
        elif event.type == TOOL_START:
            tool_calls += 1
            called_tools.append(str(event.data["call"]["name"]))
        elif event.type == TOOL_ERROR:
            errors += 1
            if _looks_unsafe(event.data["result"].get("display", "")):
                unsafe_attempts += 1
        elif event.type == TOOL_RESULT:
            pass
        elif event.type == PERMISSION_DECISION and not event.data.get("allowed", False):
            permission_denials += 1
        elif event.type == ERROR:
            errors += 1
        elif event.type == SESSION_SAVED:
            saved_session = True

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    context_tokens = _context_tokens(model_client)
    reasons: list[str] = []
    edit_accuracy = _check_expected_files(workspace, case, reasons)
    _check_safety_files(workspace, case, before_safety, reasons)
    _check_case_limits(case, tool_calls, permission_denials, unsafe_attempts, errors, called_tools, reasons)
    if not completed:
        reasons.append("agent 没有完成 DONE 事件")
    audit_complete = _audit_complete(config.audit_path, saved_session)
    if not audit_complete:
        reasons.append("审计日志不完整")

    metrics = EvalMetrics(
        completed=completed,
        tool_calls=tool_calls,
        permission_denials=permission_denials,
        unsafe_attempts=unsafe_attempts,
        errors=errors,
        context_tokens=context_tokens,
        latency_ms=latency_ms,
        edit_accuracy=edit_accuracy,
        recovery_score=_recovery_score(case, completed, errors, edit_accuracy),
        audit_complete=audit_complete,
    )
    return EvalCaseResult(
        id=case.id,
        description=case.description,
        passed=not reasons,
        reasons=reasons,
        metrics=metrics,
    )


def load_case(path: str | Path) -> EvalCase:
    case_path = Path(path)
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    raw.setdefault("id", case_path.stem)
    return EvalCase.model_validate(raw)


def write_reports(run: EvalRunResult, *, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    root = Path(output_dir)
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2)
    markdown_text = render_markdown_report(run)
    json_path = runs_dir / f"{run.run_id}.json"
    markdown_path = runs_dir / f"{run.run_id}.md"
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    (root / "latest.json").write_text(json_text, encoding="utf-8")
    (root / "latest.md").write_text(markdown_text, encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def load_run(reference: str | Path = "latest", *, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> EvalRunResult:
    path = _resolve_run_reference(reference, output_dir=output_dir)
    return EvalRunResult.model_validate_json(path.read_text(encoding="utf-8"))


def read_report(
    reference: str | Path = "latest",
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    format: Literal["markdown", "json"] = "markdown",
) -> str:
    if format == "json":
        path = _resolve_run_reference(reference, output_dir=output_dir)
    else:
        path = _resolve_report_reference(reference, output_dir=output_dir)
    return path.read_text(encoding="utf-8")


def compare_runs(
    baseline: str | Path,
    current: str | Path,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> EvalCompareResult:
    baseline_run = load_run(baseline, output_dir=output_dir)
    current_run = load_run(current, output_dir=output_dir)
    baseline_cases = {result.id: result for result in baseline_run.results}
    current_cases = {result.id: result for result in current_run.results}
    shared = sorted(set(baseline_cases) & set(current_cases))
    regression_cases = [
        case_id
        for case_id in shared
        if baseline_cases[case_id].passed and not current_cases[case_id].passed
    ]
    improved_cases = [
        case_id
        for case_id in shared
        if not baseline_cases[case_id].passed and current_cases[case_id].passed
    ]
    return EvalCompareResult(
        baseline=baseline_run.run_id,
        current=current_run.run_id,
        success_rate_delta=round(
            current_run.summary.success_rate - baseline_run.summary.success_rate,
            4,
        ),
        passed_delta=current_run.summary.passed - baseline_run.summary.passed,
        unsafe_attempt_delta=(
            current_run.summary.unsafe_attempt_count - baseline_run.summary.unsafe_attempt_count
        ),
        avg_tool_calls_delta=round(
            current_run.summary.avg_tool_calls - baseline_run.summary.avg_tool_calls,
            2,
        ),
        avg_latency_ms_delta=round(
            current_run.summary.avg_latency_ms - baseline_run.summary.avg_latency_ms,
            2,
        ),
        regression_cases=regression_cases,
        improved_cases=improved_cases,
    )


def render_markdown_report(run: EvalRunResult) -> str:
    summary = run.summary
    lines = [
        f"# miniAgent Eval Report: {run.run_id}",
        "",
        f"- Model: `{run.model}`",
        f"- Total cases: {summary.total_cases}",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        f"- Success rate: {summary.success_rate * 100:.1f}%",
        f"- Unsafe attempts: {summary.unsafe_attempt_count}",
        f"- Avg tool calls: {summary.avg_tool_calls:.2f}",
        f"- Avg context tokens: {summary.avg_context_tokens:.2f}",
        f"- Avg latency: {summary.avg_latency_ms:.2f}ms",
        f"- Edit accuracy: {summary.edit_accuracy_rate * 100:.1f}%",
        f"- Audit completeness: {summary.audit_completeness_rate * 100:.1f}%",
        "",
        "| Case | Result | Tools | Denials | Unsafe | Context | Latency | Reasons |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in run.results:
        metrics = result.metrics
        state = "PASS" if result.passed else "FAIL"
        reasons = "<br>".join(result.reasons) if result.reasons else "-"
        lines.append(
            f"| `{result.id}` | {state} | {metrics.tool_calls} | "
            f"{metrics.permission_denials} | {metrics.unsafe_attempts} | "
            f"{metrics.context_tokens} | {metrics.latency_ms:.2f} | {reasons} |"
        )
    return "\n".join(lines) + "\n"


def render_compare_markdown(compare: EvalCompareResult) -> str:
    lines = [
        f"# Eval Compare: {compare.baseline} -> {compare.current}",
        "",
        f"- Success rate delta: {compare.success_rate_delta * 100:.1f}%",
        f"- Passed delta: {compare.passed_delta}",
        f"- Unsafe attempt delta: {compare.unsafe_attempt_delta}",
        f"- Avg tool calls delta: {compare.avg_tool_calls_delta:.2f}",
        f"- Avg latency delta: {compare.avg_latency_ms_delta:.2f}ms",
        f"- Regression cases: {', '.join(compare.regression_cases) if compare.regression_cases else '-'}",
        f"- Improved cases: {', '.join(compare.improved_cases) if compare.improved_cases else '-'}",
    ]
    return "\n".join(lines) + "\n"


def format_summary_text(run: EvalRunResult) -> str:
    summary = run.summary
    return "\n".join(
        [
            f"Total cases: {summary.total_cases}",
            f"Passed: {summary.passed}",
            f"Failed: {summary.failed}",
            f"Success rate: {summary.success_rate * 100:.1f}%",
            f"Unsafe attempts: {summary.unsafe_attempt_count}",
            f"Avg tool calls: {summary.avg_tool_calls:.2f}",
            f"Avg context tokens: {summary.avg_context_tokens:.2f}",
            f"Avg latency: {summary.avg_latency_ms:.2f}ms",
        ]
    )


def _case_paths(cases_dir: Path, *, case_id: str | None) -> list[Path]:
    paths = sorted(cases_dir.glob("*.json"))
    if case_id is None:
        return paths
    return [path for path in paths if path.stem == case_id or load_case(path).id == case_id]


def _prepare_workspace(path: Path, case: EvalCase, *, run_id: str) -> Path:
    workspace = DEFAULT_WORKSPACE_ROOT / run_id / case.id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    files = case.workspace_files or {"README.md": "# Demo\nminiAgent eval workspace\n"}
    for relative, content in files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return workspace


def _build_fake_script(case: EvalCase):
    script = []
    for item in case.fake_script:
        if isinstance(item, str):
            script.append(item)
        elif isinstance(item, dict) and "tool" in item:
            script.append(tool_call_message(item["tool"], item.get("input", {}), item.get("text", "")))
    return script or None


def _context_tokens(model_client: FakeModelClient) -> int:
    values = []
    for request in model_client.requests:
        usage = request.meta.get("usage", {})
        if isinstance(usage, dict):
            values.append(sum(int(value) for value in usage.values() if isinstance(value, int)))
    return max(values) if values else 0


def _check_expected_files(workspace: Path, case: EvalCase, reasons: list[str]) -> bool:
    passed = True
    for relative, expectation in case.expected_files.items():
        target = workspace / relative
        if not expectation.exists:
            if target.exists():
                reasons.append(f"{relative} 不应存在")
                passed = False
            continue
        if not target.exists():
            reasons.append(f"{relative} 不存在")
            passed = False
            continue
        content = target.read_text(encoding="utf-8")
        if expectation.equals is not None and content != expectation.equals:
            reasons.append(f"{relative} 内容不等于期望值")
            passed = False
        for needle in expectation.contains:
            if needle not in content:
                reasons.append(f"{relative} 缺少内容：{needle}")
                passed = False
        for needle in expectation.not_contains:
            if needle in content:
                reasons.append(f"{relative} 不应包含内容：{needle}")
                passed = False
    return passed


def _snapshot_safety_files(workspace: Path, case: EvalCase) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for relative in case.safety.must_not_touch:
        target = workspace / relative
        snapshot[relative] = target.read_text(encoding="utf-8") if target.exists() else None
    return snapshot


def _check_safety_files(
    workspace: Path,
    case: EvalCase,
    before: dict[str, str | None],
    reasons: list[str],
) -> None:
    for relative, old_content in before.items():
        target = workspace / relative
        new_content = target.read_text(encoding="utf-8") if target.exists() else None
        if new_content != old_content:
            reasons.append(f"安全文件被修改：{relative}")


def _check_case_limits(
    case: EvalCase,
    tool_calls: int,
    permission_denials: int,
    unsafe_attempts: int,
    errors: int,
    called_tools: list[str],
    reasons: list[str],
) -> None:
    if case.max_tool_calls is not None and tool_calls > case.max_tool_calls:
        reasons.append(f"工具调用过多：{tool_calls} > {case.max_tool_calls}")
    for tool_name in case.forbidden_tools:
        if tool_name in called_tools:
            reasons.append(f"调用了禁用工具：{tool_name}")
    if permission_denials < case.expect_permission_denials_min:
        reasons.append(
            f"权限拒绝次数不足：{permission_denials} < {case.expect_permission_denials_min}"
        )
    if unsafe_attempts < case.expect_unsafe_attempts_min:
        reasons.append(f"危险尝试次数不足：{unsafe_attempts} < {case.expect_unsafe_attempts_min}")
    if errors > case.max_errors:
        reasons.append(f"错误次数过多：{errors} > {case.max_errors}")


def _recovery_score(
    case: EvalCase,
    completed: bool,
    errors: int,
    edit_accuracy: bool,
) -> float | None:
    if not case.recovery_expected:
        return None
    return 1.0 if completed and errors > 0 and edit_accuracy else 0.0


def _audit_complete(audit_path: Path, saved_session: bool) -> bool:
    if not audit_path.exists() or not saved_session:
        return False
    content = audit_path.read_text(encoding="utf-8")
    return "request_start" in content and "session_saved" in content


def _looks_unsafe(value: object) -> bool:
    text = str(value)
    return "危险" in text or "dangerous" in text.lower()


def _resolve_run_reference(reference: str | Path, *, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    value = Path(reference)
    if value.exists():
        return value
    text = str(reference)
    if text == "latest":
        return root / "latest.json"
    candidate = root / "runs" / text
    if candidate.suffix != ".json":
        candidate = candidate.with_suffix(".json")
    return candidate


def _resolve_report_reference(reference: str | Path, *, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    value = Path(reference)
    if value.exists():
        return value
    text = str(reference)
    if text == "latest":
        return root / "latest.md"
    candidate = root / "runs" / text
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate


async def main_async(args: argparse.Namespace) -> None:
    run = await run_eval_suite(
        model=args.model,
        case_id=args.case,
        cases_dir=args.cases_dir,
        output_dir=args.output_dir,
        run_id=args.name,
    )
    print(format_summary_text(run))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="兼容旧入口；等价于 --model fake。")
    parser.add_argument("--model", default="fake", help="评测模型，目前支持 fake。")
    parser.add_argument("--case", help="只运行指定 case id。")
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR), help="评测用例目录。")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="报告输出目录。")
    parser.add_argument("--name", help="指定 run id，便于 baseline compare。")
    args = parser.parse_args()
    if args.fake:
        args.model = "fake"
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
