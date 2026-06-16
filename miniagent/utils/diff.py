from __future__ import annotations

import difflib


def unified_diff(old: str, new: str, *, fromfile: str = "before", tofile: str = "after") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
