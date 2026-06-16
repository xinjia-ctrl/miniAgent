from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.metrics import EvalMetrics
from pycode_agent.config import default_config
from pycode_agent.engine import QueryEngine
from pycode_agent.events import DONE, ERROR, PERMISSION_DECISION, TOOL_ERROR, TOOL_RESULT
from pycode_agent.model import FakeModelClient, tool_call_message


async def run_case(path: Path) -> dict[str, object]:
    case = json.loads(path.read_text(encoding="utf-8"))
    workspace = _prepare_workspace(path, case)
    config = default_config(cwd=workspace, permission_mode=case.get("permission_mode", "default"))
    model = FakeModelClient(_build_fake_script(case))
    engine = QueryEngine(config=config, model_client=model)
    completed = False
    tool_calls = 0
    denials = 0
    errors = 0
    blocked_danger = False
    async for event in engine.submit(case["prompt"]):
        if event.type == DONE:
            completed = True
        elif event.type in {TOOL_RESULT, TOOL_ERROR}:
            tool_calls += 1
            if event.type == TOOL_ERROR:
                errors += 1
                display = event.data["result"].get("display", "")
                blocked_danger = blocked_danger or "危险" in display or "拒绝" in display
        elif event.type == PERMISSION_DECISION and not event.data.get("allowed", False):
            denials += 1
            blocked_danger = True
        elif event.type == ERROR:
            errors += 1
    expected_file = case.get("expected_file_modified")
    expected_file_modified = False
    if expected_file:
        target = workspace / expected_file
        expected_file_modified = target.exists() and target.read_text(encoding="utf-8") != case[
            "workspace_files"
        ].get(expected_file, "")
    metrics = EvalMetrics(completed, tool_calls, denials, errors)
    metrics.expected_file_modified = expected_file_modified
    metrics.dangerous_behavior_blocked = blocked_danger
    return {"case": path.name, "metrics": metrics.as_dict()}


def _prepare_workspace(path: Path, case: dict[str, object]) -> Path:
    if "workspace_files" not in case:
        return ROOT
    workspace = ROOT / ".pycode_agent" / "eval_workspaces" / path.stem
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    for relative, content in case["workspace_files"].items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return workspace


def _build_fake_script(case: dict[str, object]):
    script = []
    for item in case.get("fake_script", []):
        if isinstance(item, str):
            script.append(item)
        elif isinstance(item, dict) and "tool" in item:
            script.append(tool_call_message(item["tool"], item.get("input", {}), item.get("text", "")))
    return script or None


async def main_async() -> None:
    cases_dir = Path(__file__).parent / "cases"
    for path in sorted(cases_dir.glob("*.json")):
        print(json.dumps(await run_case(path), ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="使用 FakeModelClient 运行。")
    parser.parse_args()
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
