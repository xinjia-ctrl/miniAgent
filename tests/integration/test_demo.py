from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_make_demo_generates_session_and_report(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = tmp_path / "real_project_demo"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "make_demo.py"),
            "--output-dir",
            str(output_dir),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "Demo generated" in result.stdout
    assert "return subtotal * (1 - discount_percent / 100)" in (
        output_dir / "workspace" / "src" / "shopcart" / "pricing.py"
    ).read_text(encoding="utf-8")

    summary = json.loads((output_dir / "demo_summary.json").read_text(encoding="utf-8"))
    session_export = json.loads((output_dir / "session_export.json").read_text(encoding="utf-8"))
    report = (output_dir / "README.md").read_text(encoding="utf-8")
    audit_report = (output_dir / "audit_report.md").read_text(encoding="utf-8")

    assert {"repo_map", "read_file", "edit_file", "shell"}.issubset(summary["tool_calls"])
    assert session_export["snapshot"]["id"] == summary["session_id"]
    assert "python -m pytest tests/test_pricing.py" in report
    assert "tool_calls:" in audit_report
