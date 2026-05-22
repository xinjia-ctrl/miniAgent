from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from miniagent.benchmarks import run_benchmarks


def main():
    parser = argparse.ArgumentParser(description="运行 miniAgent 确定性基准测试")
    parser.add_argument("--output", help="可选，写入 JSON 结果文件")
    args = parser.parse_args()
    summary = run_benchmarks(output_path=args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["passed"] == summary["total"] else 1)


if __name__ == "__main__":
    main()
