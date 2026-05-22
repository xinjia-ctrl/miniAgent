"""Agent Runtime：模型循环、工具调度、运行记录和会话写入。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .context import trim_messages
from .run_store import RunStore
from .session import save_message


@dataclass
class ToolExecution:
    tool_call: object
    name: str
    args: dict
    before_diff: str = ""
    before_status: str = ""
    snapshots: dict | None = None
    result: str | None = None


def assistant_extra(msg) -> dict:
    """提取需要回传给模型的 assistant 扩展字段。"""
    extra = {}
    if getattr(msg, "reasoning_content", None):
        extra["reasoning_content"] = msg.reasoning_content
    return extra


class AgentRuntime:
    """CLI 之外的 agent 控制层。

    CLI 负责终端输入输出；Runtime 负责每轮模型调用、工具执行顺序、
    会话落盘和 run trace。这样后续测试可以绕开交互终端，直接验证核心行为。
    """

    def __init__(
        self,
        backend,
        tools: list[dict],
        func_map: dict[str, Callable],
        refresh_system_message: Callable[[list[dict]], None],
        check_permission: Callable[[str, dict, str | None], tuple[bool, str]],
        log_tool_call: Callable[[str | None, str, dict], None],
        log_tool_result: Callable[[str | None, str, str], None],
        format_tool_call: Callable[[str, dict], str] | None = None,
        print_tool_result: Callable[[str], None] | None = None,
        git_diff_text: Callable[[], str] | None = None,
        git_status_short: Callable[[], str] | None = None,
        paths_for_edit_tool: Callable[[str, dict], list] | None = None,
        snapshot_paths: Callable[[list], dict] | None = None,
        review_diff_after_edit: Callable[[str | None, str, str, str, dict], str] | None = None,
        edit_tools: set[str] | None = None,
        parallel_safe_tools: set[str] | None = None,
        run_store: RunStore | None = None,
        verbose_tools: Callable[[], bool] | None = None,
    ):
        self.backend = backend
        self.tools = tools
        self.func_map = dict(func_map)
        self.refresh_system_message = refresh_system_message
        self.check_permission = check_permission
        self.log_tool_call = log_tool_call
        self.log_tool_result = log_tool_result
        self.format_tool_call = format_tool_call or self._default_format_tool_call
        self.print_tool_result = print_tool_result or self._default_print_tool_result
        self.git_diff_text = git_diff_text or (lambda: "")
        self.git_status_short = git_status_short or (lambda: "")
        self.paths_for_edit_tool = paths_for_edit_tool or (lambda _name, _args: [])
        self.snapshot_paths = snapshot_paths or (lambda _paths: {})
        self.review_diff_after_edit = review_diff_after_edit or (
            lambda _session_id, _name, _before_diff, _before_status, _snapshots: "skipped"
        )
        self.edit_tools = set(edit_tools or ())
        self.parallel_safe_tools = set(parallel_safe_tools or ())
        self.run_store = run_store or RunStore()
        self.verbose_tools = verbose_tools or (lambda: False)

    @staticmethod
    def _default_format_tool_call(name: str, args: dict) -> str:
        return f"{name}({json.dumps(args, ensure_ascii=False)})"

    @staticmethod
    def _default_print_tool_result(result: str) -> None:
        print(str(result))

    def call_ai(self, messages: list[dict]):
        """调模型，返回 AssistantMessage。"""
        self.refresh_system_message(messages)
        return self.backend.chat(trim_messages(messages), tools=self.tools)

    def call_ai_stream(self, messages: list[dict]):
        """流式调模型，返回聚合后的 AssistantMessage。"""
        self.refresh_system_message(messages)
        return self.backend.chat_stream(
            trim_messages(messages),
            tools=self.tools,
            on_text=lambda text: print(text, end="", flush=True),
        )

    def run_tool_function(self, name: str, args: dict) -> str:
        func = self.func_map.get(name)
        if not func:
            return f"未知工具: {name}"
        try:
            return str(func(**(args or {})))
        except Exception as exc:
            return f"工具执行失败: {type(exc).__name__}: {exc}"

    def exec_direct(self, name: str, args: dict, session_id: str | None = None) -> str:
        """直接执行 REPL 工具命令。"""
        run_id = self.run_store.new_run_id()
        self.run_store.write_status(run_id, {
            "status": "running",
            "entry": "direct_tool",
            "session_id": session_id,
            "tool": name,
        })
        self.run_store.append_trace(run_id, "direct_tool_requested", {"tool": name, "args": args})

        if name not in self.func_map:
            result = f"未知工具: {name}"
            print(result)
            self._finish_run(run_id, "error", result, tool=name)
            return result

        allowed, reason = self.check_permission(name, args, session_id)
        if not allowed:
            print(reason)
            self._finish_run(run_id, "permission_denied", reason, tool=name)
            return reason

        self.log_tool_call(session_id, name, args)
        before_diff = self.git_diff_text() if name in self.edit_tools else ""
        before_status = self.git_status_short() if name in self.edit_tools else ""
        snapshots = (
            self.snapshot_paths(self.paths_for_edit_tool(name, args))
            if name in self.edit_tools else {}
        )
        result = self.run_tool_function(name, args)
        self.log_tool_result(session_id, name, result)
        print(result)

        if name in self.edit_tools and not str(result).startswith("错误"):
            decision = self.review_diff_after_edit(session_id, name, before_diff, before_status, snapshots)
            if decision == "rolled_back":
                result = f"{result}\n\n审批结果：用户已回滚本次文件改动"
            elif decision in ("accepted", "continue"):
                result = f"{result}\n\n审批结果：{decision}"

        self._finish_run(run_id, "success", result, tool=name)
        return str(result)

    def handle_tool_calls(self, msg, messages: list[dict], session_id: str, max_steps: int = 15):
        """ReAct 循环：反复调工具直到 AI 给出最终回答。"""
        run_id = self.run_store.new_run_id()
        self.run_store.write_status(run_id, {
            "status": "running",
            "entry": "assistant_loop",
            "session_id": session_id,
            "step": 0,
        })

        step = 0
        while step < max_steps:
            step += 1
            self.run_store.write_status(run_id, {
                "status": "running",
                "entry": "assistant_loop",
                "session_id": session_id,
                "step": step,
            })

            if not msg.tool_calls:
                final = msg.content or ""
                self._finish_run(run_id, "success", final, step=step)
                return final, assistant_extra(msg), msg.streamed

            assistant_msg = self._assistant_tool_message(msg)
            messages.append(assistant_msg)
            save_message(
                session_id,
                "assistant",
                msg.content or "",
                tool_calls=assistant_msg["tool_calls"],
                reasoning_content=assistant_msg.get("reasoning_content"),
            )
            self.run_store.append_trace(
                run_id,
                "assistant_tool_calls",
                {"step": step, "tool_count": len(msg.tool_calls)},
            )

            prepared_calls = self._prepare_tool_calls(run_id, msg, messages, session_id)
            self._execute_prepared_calls(prepared_calls)
            self._record_tool_results(prepared_calls, messages, session_id, run_id)

            print("AI: ", end="", flush=True)
            msg = self.call_ai_stream(messages)
            if msg.streamed:
                print()
            elif not msg.tool_calls and msg.content:
                print(msg.content)

        final = msg.content or "(达到最大步骤数)"
        self._finish_run(run_id, "step_limit", final, step=step)
        return final, assistant_extra(msg), msg.streamed

    def _assistant_tool_message(self, msg) -> dict:
        assistant_msg = {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        }
        if getattr(msg, "reasoning_content", None):
            assistant_msg["reasoning_content"] = msg.reasoning_content
        return assistant_msg

    def _prepare_tool_calls(self, run_id: str, msg, messages: list[dict], session_id: str) -> list[ToolExecution]:
        prepared_calls = []
        for tc in msg.tool_calls:
            name = tc.name
            try:
                args = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError as exc:
                result = f"工具参数 JSON 解析失败: {exc}"
                print(f"  → {name}(参数解析失败)")
                self.print_tool_result(result)
                self._append_tool_message(messages, session_id, tc.id, name, result)
                self.run_store.append_trace(
                    run_id,
                    "tool_arguments_invalid",
                    {"tool": name, "error": str(exc)},
                )
                continue

            if self.verbose_tools():
                print(f"  → {name}({json.dumps(args, ensure_ascii=False)})")
            else:
                print(f"  → {self.format_tool_call(name, args)}")

            allowed, reason = self.check_permission(name, args, session_id)
            if not allowed:
                self.print_tool_result(reason)
                self._append_tool_message(messages, session_id, tc.id, name, reason)
                self.run_store.append_trace(
                    run_id,
                    "tool_permission_denied",
                    {"tool": name, "args": args, "reason": reason},
                )
                continue

            self.log_tool_call(session_id, name, args)
            prepared_calls.append(ToolExecution(
                tool_call=tc,
                name=name,
                args=args,
                before_diff=self.git_diff_text() if name in self.edit_tools else "",
                before_status=self.git_status_short() if name in self.edit_tools else "",
                snapshots=(
                    self.snapshot_paths(self.paths_for_edit_tool(name, args))
                    if name in self.edit_tools else {}
                ),
            ))
        return prepared_calls

    def _execute_prepared_calls(self, prepared_calls: list[ToolExecution]) -> None:
        if len(prepared_calls) > 1 and all(item.name in self.parallel_safe_tools for item in prepared_calls):
            print(f"  并行执行 {len(prepared_calls)} 个工具调用")
            with ThreadPoolExecutor(max_workers=min(8, len(prepared_calls))) as executor:
                futures = [
                    executor.submit(self.run_tool_function, item.name, item.args)
                    for item in prepared_calls
                ]
                for item, future in zip(prepared_calls, futures):
                    item.result = future.result()
            return

        for item in prepared_calls:
            item.result = self.run_tool_function(item.name, item.args)

    def _record_tool_results(
        self,
        prepared_calls: list[ToolExecution],
        messages: list[dict],
        session_id: str,
        run_id: str,
    ) -> None:
        for item in prepared_calls:
            result = item.result or ""
            self.print_tool_result(result)
            self.log_tool_result(session_id, item.name, result)

            if item.name in self.edit_tools and not str(result).startswith("错误"):
                decision = self.review_diff_after_edit(
                    session_id,
                    item.name,
                    item.before_diff,
                    item.before_status,
                    item.snapshots or {},
                )
                if decision == "rolled_back":
                    result = f"{result}\n\n审批结果：用户已回滚本次文件改动"
                elif decision in ("accepted", "continue"):
                    result = f"{result}\n\n审批结果：{decision}"

            self._append_tool_message(messages, session_id, item.tool_call.id, item.name, result)
            self.run_store.append_trace(
                run_id,
                "tool_executed",
                {"tool": item.name, "args": item.args, "result_preview": str(result)[:500]},
            )

    @staticmethod
    def _append_tool_message(messages: list[dict], session_id: str, tool_call_id: str, name: str, result: str) -> None:
        content = str(result).encode("utf-8", errors="replace").decode("utf-8")
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
        save_message(session_id, "tool", content, tool_call_id=tool_call_id, name=name)

    def _finish_run(self, run_id: str, status: str, final: str, **extra) -> None:
        payload = {
            "status": status,
            "final_answer": final,
            **extra,
        }
        self.run_store.write_status(run_id, payload)
        self.run_store.write_report(run_id, payload)
        self.run_store.append_trace(run_id, "run_finished", payload)
