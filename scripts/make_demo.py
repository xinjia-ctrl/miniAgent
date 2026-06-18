from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from miniagent.audit_report import build_session_audit_report, render_audit_report
from miniagent.config import default_config
from miniagent.engine import QueryEngine
from miniagent.events import EngineEvent
from miniagent.messages import message_text
from miniagent.model import FakeModelClient, tool_call_message
from miniagent.storage import SessionStorage


TEMPLATE_DIR = REPO_ROOT / "demos" / "real_project_demo" / "template"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "demos" / "generated" / "real_project_demo"

DEMO_PROMPT = (
    "请阅读这个小项目，修复折扣计算 bug，运行测试，并提交一份简短报告。"
)

FINAL_REPORT = """Demo 报告：
- 已通过 repo_map 了解项目结构。
- 已读取 README、src/shopcart/pricing.py 和 tests/test_pricing.py。
- 已修复 apply_discount 把百分比当成固定金额相减的问题。
- 已运行 python -m pytest tests/test_pricing.py，测试通过。
"""


@dataclass(frozen=True)
class DemoArtifacts:
    output_dir: Path
    workspace: Path
    session_id: str
    session_export: Path
    event_stream: Path
    audit_report: Path
    demo_readme: Path
    summary: Path


async def build_demo(output_dir: Path = DEFAULT_OUTPUT_DIR) -> DemoArtifacts:
    output_dir = output_dir.resolve()
    workspace = output_dir / "workspace"
    _copy_template(TEMPLATE_DIR, workspace)

    config = default_config(
        cwd=workspace,
        permission_mode="bypass",
        max_turns=8,
        max_result_chars=10000,
    )
    model = FakeModelClient(_demo_script())
    engine = QueryEngine(config=config, model_client=model)

    events: list[EngineEvent] = []
    async for event in engine.submit(DEMO_PROMPT):
        events.append(event)

    _assert_demo_succeeded(engine)

    storage = SessionStorage(config.resolved_data_dir)
    export = storage.export(engine.session_id)
    audit = build_session_audit_report(
        storage=storage,
        audit_path=config.audit_path,
        session_id=engine.session_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    session_export = output_dir / "session_export.json"
    event_stream = output_dir / "event_stream.json"
    audit_report = output_dir / "audit_report.md"
    demo_readme = output_dir / "README.md"
    summary = output_dir / "demo_summary.json"

    _write_json(session_export, export)
    _write_json(event_stream, [event.model_dump(mode="json") for event in events])
    audit_report.write_text(render_audit_report(audit), encoding="utf-8")
    demo_readme.write_text(_render_demo_readme(engine, config.audit_path), encoding="utf-8")
    _write_json(
        summary,
        {
            "session_id": engine.session_id,
            "workspace": str(workspace),
            "session_export": str(session_export),
            "event_stream": str(event_stream),
            "audit_report": str(audit_report),
            "demo_readme": str(demo_readme),
            "tool_calls": [call["name"] for call in engine.tool_calls],
            "final_report": message_text(engine.messages[-1]) if engine.messages else "",
        },
    )

    return DemoArtifacts(
        output_dir=output_dir,
        workspace=workspace,
        session_id=engine.session_id,
        session_export=session_export,
        event_stream=event_stream,
        audit_report=audit_report,
        demo_readme=demo_readme,
        summary=summary,
    )


def _copy_template(template_dir: Path, workspace: Path) -> None:
    for source in template_dir.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(template_dir)
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


def _demo_script():
    return [
        tool_call_message(
            "repo_map",
            {"path": ".", "max_files": 40, "max_symbols_per_file": 6},
            "先生成 repo map，了解项目结构。",
        ),
        tool_call_message(
            "read_file",
            {"file_path": "README.md"},
            "读取项目说明。",
        ),
        tool_call_message(
            "read_file",
            {"file_path": "src/shopcart/pricing.py"},
            "读取折扣实现。",
        ),
        tool_call_message(
            "read_file",
            {"file_path": "tests/test_pricing.py"},
            "读取测试，确认期望行为。",
        ),
        tool_call_message(
            "edit_file",
            {
                "file_path": "src/shopcart/pricing.py",
                "old_string": "    return subtotal - discount_percent",
                "new_string": "    return subtotal * (1 - discount_percent / 100)",
            },
            "修复百分比折扣计算。",
        ),
        tool_call_message(
            "shell",
            {"command": "python -m pytest tests/test_pricing.py", "timeout_seconds": 60},
            "运行项目测试。",
        ),
        FINAL_REPORT,
    ]


def _assert_demo_succeeded(engine: QueryEngine) -> None:
    tools = [call["name"] for call in engine.tool_calls]
    required = {"repo_map", "read_file", "edit_file", "shell"}
    missing = sorted(required.difference(tools))
    if missing:
        raise RuntimeError(f"demo 缺少必要工具调用：{', '.join(missing)}")

    shell_results = [
        result
        for call, result in zip(engine.tool_calls, engine.tool_results, strict=False)
        if call["name"] == "shell"
    ]
    if not shell_results:
        raise RuntimeError("demo 没有运行测试命令")
    if shell_results[-1].get("is_error"):
        raise RuntimeError("demo 测试命令失败")


def _render_demo_readme(engine: QueryEngine, audit_path: Path) -> str:
    final_text = message_text(engine.messages[-1]) if engine.messages else ""
    tool_lines = "\n".join(
        f"- {index}. {call['name']}: `{call.get('input', {})}`"
        for index, call in enumerate(engine.tool_calls, start=1)
    )
    return f"""# miniAgent Real Project Demo

本 demo 由 `scripts/make_demo.py` 自动生成，展示 miniAgent 在一个真实小项目中完成读项目、修 bug、跑测试和提交报告的端到端流程。

## Session

- session_id: `{engine.session_id}`
- audit_log: `{audit_path}`
- workspace: `{engine.config.cwd}`

## Tool Calls

{tool_lines}

## Final Report

```text
{final_text.strip()}
```

## Inspect

```powershell
python -m miniagent sessions export --cwd "{engine.config.cwd}" --last
python -m miniagent audit show {engine.session_id} --cwd "{engine.config.cwd}"
```
"""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the miniAgent real-project demo.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Demo output directory. Defaults to demos/generated/real_project_demo.",
    )
    args = parser.parse_args(argv)

    artifacts = asyncio.run(build_demo(args.output_dir))
    print("Demo generated")
    print(f"workspace: {artifacts.workspace}")
    print(f"session_id: {artifacts.session_id}")
    print(f"session_export: {artifacts.session_export}")
    print(f"audit_report: {artifacts.audit_report}")
    print(f"demo_readme: {artifacts.demo_readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
