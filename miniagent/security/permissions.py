from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from miniagent.security.paths import sensitive_path_reason
from miniagent.security.shell import ShellClassification, classify_shell_command


class PermissionRule(BaseModel):
    action: Literal["allow", "deny"]
    tool: str = "*"
    pattern: str = "*"
    reason: str = ""


def classify_tool_request(tool_name: str, input_data: object, cwd: str) -> dict[str, Any]:
    target = tool_request_target(tool_name, input_data)
    classification: dict[str, Any] = {"target": target, "risk": "unknown"}
    if tool_name == "shell":
        shell = classify_shell_command(str(_input_value(input_data, "command") or ""))
        classification.update({"risk": shell.risk.value, "reason": shell.reason})
    path_reason = sensitive_tool_path_reason(input_data, cwd)
    if path_reason:
        classification.update({"risk": "sensitive_path", "reason": path_reason})
    return classification


def hard_deny_reason(tool_name: str, input_data: object) -> str | None:
    if tool_name != "shell":
        return None
    shell = classify_shell_command(str(_input_value(input_data, "command") or ""))
    if shell.is_dangerous:
        return shell.reason
    return None


def sensitive_tool_path_reason(input_data: object, cwd: str) -> str | None:
    for key in ("file_path", "path"):
        raw_path = _input_value(input_data, key)
        if not raw_path:
            continue
        root = Path(cwd).resolve(strict=False)
        candidate = Path(str(raw_path))
        resolved = candidate if candidate.is_absolute() else root / candidate
        reason = sensitive_path_reason(resolved.resolve(strict=False))
        if reason:
            return reason
    return None


def match_session_rule(
    rules: list[dict[str, Any]] | None,
    *,
    tool_name: str,
    input_data: object,
    action: Literal["allow", "deny"] | None = None,
) -> PermissionRule | None:
    target = tool_request_target(tool_name, input_data)
    for raw_rule in rules or []:
        rule = PermissionRule.model_validate(raw_rule)
        if action and rule.action != action:
            continue
        if not fnmatch.fnmatch(tool_name, rule.tool):
            continue
        if fnmatch.fnmatch(target, rule.pattern):
            return rule
    return None


def tool_request_target(tool_name: str, input_data: object) -> str:
    if tool_name == "shell":
        return str(_input_value(input_data, "command") or "")
    for key in ("file_path", "path"):
        value = _input_value(input_data, key)
        if value:
            return str(value)
    return json.dumps(_input_dict(input_data), ensure_ascii=False, sort_keys=True)


def _input_value(input_data: object, key: str) -> Any:
    if isinstance(input_data, BaseModel):
        return getattr(input_data, key, None)
    if isinstance(input_data, dict):
        return input_data.get(key)
    return getattr(input_data, key, None)


def _input_dict(input_data: object) -> dict[str, Any]:
    if isinstance(input_data, BaseModel):
        return input_data.model_dump(mode="json")
    if isinstance(input_data, dict):
        return dict(input_data)
    return {}
