"""Benchmark results (json, see `build_local.sh bench`) as a markdown report.

    python benchmarks/report.py <result.json>... [--out report.md]

One table per result file (architecture / browser / mode), one row per
benchmark. Used by the CI to show the results on the job's summary page; the
times are of a shared CI runner, compare the rows of one run rather than
absolute numbers of different runs.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import format_time  # noqa: E402  (plain python, no pyjs needed)


def table(result):
    """markdown table of one result file"""
    rows = [
        "| benchmark | median / op | min / op | ops / s | stddev |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in result["results"]:
        if "error" in r:
            rows.append(f"| `{r['name']}` | **error:** {r['error']} | | | |")
            continue
        spread = 100 * r["stddev"] / r["mean"] if r["mean"] else 0
        rows.append(
            f"| `{r['name']}` | {format_time(r['median']).strip()} | "
            f"{format_time(r['min']).strip()} | {r['ops_per_sec']:,.0f} | {spread:.1f} % |"
        )
    return "\n".join(rows)


def report(paths):
    """the markdown report of all result files"""
    parts = ["# pyjs benchmarks"]
    for path in paths:
        result = json.loads(Path(path).read_text())
        build = result.get("build", {})
        title = " / ".join(build.get(k, "?") for k in ("wasm_type", "browser", "mode"))
        env = result.get("environment", {})
        parts.append(f"## {title}")
        parts.append(
            f"git `{build.get('git_rev', '?')}`, "
            f"{env.get('pointer_bits', '?')} bit, {env.get('user_agent', '')}"
        )
        if not result.get("ok", False):
            parts.append("**some benchmarks failed**")
        parts.append(table(result))
    return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", nargs="+", help="result json files")
    parser.add_argument("--out", help="write the report here (default: stdout)")
    args = parser.parse_args()
    text = report(args.results)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
