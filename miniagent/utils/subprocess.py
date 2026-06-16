from __future__ import annotations

import asyncio
import platform
import subprocess
from pathlib import Path

from pydantic import BaseModel

from miniagent.utils.text import clip_text


class SubprocessResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


async def run_subprocess(
    command: str,
    *,
    cwd: str | Path,
    timeout_seconds: int = 30,
    max_output_chars: int = 6000,
) -> SubprocessResult:
    return await asyncio.to_thread(
        _run_subprocess_sync,
        command,
        cwd,
        timeout_seconds,
        max_output_chars,
    )


def _run_subprocess_sync(
    command: str,
    cwd: str | Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> SubprocessResult:
    if platform.system().lower().startswith("windows"):
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    else:
        args = ["sh", "-lc", command]

    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return SubprocessResult(
            command=command,
            exit_code=completed.returncode,
            stdout=clip_text(completed.stdout, max_output_chars),
            stderr=clip_text(completed.stderr, max_output_chars),
        )
    except subprocess.TimeoutExpired as exc:
        return SubprocessResult(
            command=command,
            exit_code=-1,
            stdout=clip_text((exc.stdout or ""), max_output_chars),
            stderr=clip_text((exc.stderr or ""), max_output_chars),
            timed_out=True,
        )
