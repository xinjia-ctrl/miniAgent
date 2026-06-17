from __future__ import annotations

import asyncio
import json

from typer.testing import CliRunner

from evals.runner import (
    DEFAULT_CASES_DIR,
    compare_runs,
    load_run,
    read_report,
    run_eval_suite,
)
from miniagent.cli import app


def test_default_eval_suite_has_at_least_30_cases() -> None:
    cases = sorted(DEFAULT_CASES_DIR.glob("*.json"))

    assert len(cases) >= 30


def test_eval_runner_writes_json_markdown_and_compare(tmp_path) -> None:
    baseline = asyncio.run(
        run_eval_suite(
            model="fake",
            case_id="read_project",
            output_dir=tmp_path,
            run_id="baseline",
        )
    )
    current = asyncio.run(
        run_eval_suite(
            model="fake",
            case_id="read_project",
            output_dir=tmp_path,
            run_id="current",
        )
    )

    report = read_report("latest", output_dir=tmp_path)
    loaded = load_run("current", output_dir=tmp_path)
    compare = compare_runs("baseline", "current", output_dir=tmp_path)

    assert baseline.summary.total_cases == 1
    assert current.summary.passed == 1
    assert "# miniAgent Eval Report" in report
    assert loaded.run_id == "current"
    assert compare.passed_delta == 0
    assert (tmp_path / "runs" / "baseline.json").exists()
    assert (tmp_path / "runs" / "current.md").exists()


def test_cli_evals_run_and_report(tmp_path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "evals",
            "run",
            "--model",
            "fake",
            "--case",
            "read_project",
            "--name",
            "cli_eval",
            "--output-dir",
            str(tmp_path),
        ],
    )
    report = runner.invoke(app, ["evals", "report", "--output-dir", str(tmp_path)])
    json_report = runner.invoke(
        app,
        ["evals", "report", "--format", "json", "--output-dir", str(tmp_path)],
    )

    assert run.exit_code == 0
    assert "Total cases: 1" in run.output
    assert report.exit_code == 0
    assert "# miniAgent Eval Report" in report.output
    assert json_report.exit_code == 0
    assert json.loads(json_report.output)["run_id"] == "cli_eval"
