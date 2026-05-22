"""确定性基准测试框架，用于量化 Runtime 和工具链回归。"""

from __future__ import annotations

import json
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from .models import AssistantMessage, FakeModelClient, ToolCall
from .run_store import RunStore
from .runtime import AgentRuntime
from . import session as session_module


@dataclass
class BenchmarkResult:
    name: str
    passed: bool
    metrics: dict
    reason: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "passed": self.passed,
            "metrics": self.metrics,
            "reason": self.reason,
        }


def _runtime(tmp_path, backend, func_map, parallel_safe_tools=None):
    return AgentRuntime(
        backend=backend,
        tools=[],
        func_map=func_map,
        refresh_system_message=lambda messages: None,
        check_permission=lambda name, args, session_id=None: (True, "allowed"),
        log_tool_call=lambda session_id, name, args: None,
        log_tool_result=lambda session_id, name, result: None,
        print_tool_result=lambda result: None,
        run_store=RunStore(tmp_path / "runs"),
        parallel_safe_tools=parallel_safe_tools or set(),
    )


def bench_parallel_order(tmp_path):
    session_module.SESSION_DIR = tmp_path / "sessions"
    session_id = session_module.create_session()
    backend = FakeModelClient([AssistantMessage(content="done")])
    runtime = _runtime(
        tmp_path,
        backend,
        {"first": lambda: "one", "second": lambda: "two"},
        parallel_safe_tools={"first", "second"},
    )
    messages = [{"role": "system", "content": "sys"}]
    first = AssistantMessage(tool_calls=[
        ToolCall("call_1", "first", "{}"),
        ToolCall("call_2", "second", "{}"),
    ])
    runtime.handle_tool_calls(first, messages, session_id)
    tool_messages = [msg["content"] for msg in messages if msg.get("role") == "tool"]
    return BenchmarkResult(
        name="parallel_order",
        passed=tool_messages == ["one", "two"],
        metrics={"tool_messages": len(tool_messages), "model_calls": len(backend.calls)},
        reason=str(tool_messages),
    )


def bench_repeated_call_guard(tmp_path):
    session_module.SESSION_DIR = tmp_path / "sessions"
    session_id = session_module.create_session()
    backend = FakeModelClient([
        AssistantMessage(tool_calls=[ToolCall("call_2", "read_file", json.dumps({"path": "README.md"}))]),
        AssistantMessage(content="done"),
    ])
    runtime = _runtime(tmp_path, backend, {"read_file": lambda path: "content"})
    messages = [{"role": "system", "content": "sys"}]
    first = AssistantMessage(tool_calls=[ToolCall("call_1", "read_file", json.dumps({"path": "README.md"}))])
    runtime.handle_tool_calls(first, messages, session_id)
    contents = [msg["content"] for msg in messages if msg.get("role") == "tool"]
    passed = len(contents) == 2 and "重复调用" in contents[-1]
    return BenchmarkResult(
        name="repeated_call_guard",
        passed=passed,
        metrics={"tool_messages": len(contents), "model_calls": len(backend.calls)},
        reason=contents[-1] if contents else "no tool messages",
    )


def bench_result_clipping(tmp_path):
    runtime = _runtime(tmp_path, FakeModelClient([]), {"long": lambda: "x" * 100000})
    result = runtime.run_tool_function("long", {})
    return BenchmarkResult(
        name="result_clipping",
        passed=len(result) < 70000 and "工具结果过长" in result,
        metrics={"result_chars": len(result)},
        reason=result[-80:],
    )


BENCHMARKS = (
    bench_parallel_order,
    bench_repeated_call_guard,
    bench_result_clipping,
)


def run_benchmarks(output_path=None, work_dir=None):
    root = Path(work_dir or Path.cwd() / ".mini" / "benchmarks")
    tmp_path = root / ("bench_" + uuid.uuid4().hex[:8])
    tmp_path.mkdir(parents=True, exist_ok=True)
    with redirect_stdout(StringIO()):
        results = [bench(tmp_path).to_dict() for bench in BENCHMARKS]

    summary = {
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "results": results,
    }
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
