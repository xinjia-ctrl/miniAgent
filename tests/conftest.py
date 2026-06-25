from __future__ import annotations

import itertools
import re
import shutil
import uuid
from pathlib import Path

import pytest

from miniagent.config import default_config
from miniagent.tool_base import ToolContext
from miniagent.tools import builtin_registry


_COUNTER = itertools.count()
_BASE_TMP = Path(__file__).resolve().parents[1] / "test_workspaces"


@pytest.fixture()
def tmp_path(request) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)[-90:]
    path = _BASE_TMP / f"{next(_COUNTER):03d}_{uuid.uuid4().hex[:8]}_{name}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_user_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MINIAGENT_CONFIG_DIR", str(tmp_path / "user-config"))


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Demo\nhello agent\n", encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def registry():
    return builtin_registry()


@pytest.fixture()
def config(workspace: Path):
    return default_config(cwd=workspace, permission_mode="bypass")


@pytest.fixture()
def tool_context(workspace: Path):
    return ToolContext(
        cwd=str(workspace),
        session_id="sess_test",
        permission_mode="bypass",
        max_result_chars=6000,
    )
