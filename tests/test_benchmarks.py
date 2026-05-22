from miniagent.benchmarks import run_benchmarks


def test_benchmarks_pass():
    summary = run_benchmarks()
    assert summary["passed"] == summary["total"]
