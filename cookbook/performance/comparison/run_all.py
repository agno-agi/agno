"""
Comparison Suite Runner
=======================

Runs every cross-framework comparison benchmark sequentially, each in a
fresh Python process, and collects results plus framework versions into
results/comparison/summary.json (relative to the parent suite).

Run with the performance environment (created by ./scripts/perf_setup.sh):

    .venvs/perfenv/bin/python cookbook/performance/comparison/run_all.py
    .venvs/perfenv/bin/python cookbook/performance/comparison/run_all.py --quick
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from _compare import get_machine_info, print_summary_table
from report import COMPARISON_TABLE_ORDER, UNIT_SCALE, comparison_groups

# ---------------------------------------------------------------------------
# Configuration: benchmarks run in this order, one process at a time
# ---------------------------------------------------------------------------
BENCHMARK_FILES = [
    "import_time_comparison.py",
    "agno_instantiation.py",
    "langgraph_instantiation.py",
    "pydantic_ai_instantiation.py",
    "crewai_instantiation.py",
    "run_overhead_comparison.py",
    "tool_run_comparison.py",
    "multi_turn_comparison.py",
    "long_conversation_comparison.py",
    "durable_conversation_comparison.py",
]

FRAMEWORK_PACKAGES = ["agno", "langgraph", "langchain-openai", "pydantic-ai", "crewai"]

SUITE_DIR = Path(__file__).parent
RESULTS_DIR = SUITE_DIR.parent / "results" / "comparison"


def framework_versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    versions = {}
    for package in FRAMEWORK_PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


# ---------------------------------------------------------------------------
# Agno-versus-frameworks Table
# ---------------------------------------------------------------------------
def print_agno_vs_table(benchmarks: dict, versions: dict) -> None:
    """One row per metric, one column per framework, every non-Agno cell
    carrying its multiple of the Agno value. Shares the metric definitions
    with report.py so the terminal and the HTML report cannot diverge."""
    from rich.console import Console
    from rich.table import Table

    groups_by_key = {group["key"]: group for group in comparison_groups(versions)}
    ordered = [
        groups_by_key[key] for key in COMPARISON_TABLE_ORDER if key in groups_by_key
    ]
    if not ordered:
        return

    table = Table(
        title="Agno versus other frameworks",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Metric", style="cyan")
    for _, label, series in ordered[0]["rows"]:
        table.add_column(
            label, justify="right", style="green" if series == "sync" else None
        )

    for group in ordered:
        measure = group["measure"]
        unit = group["unit"]
        stat_key = "median_run_time" if measure == "time" else "median_memory_usage"
        baseline_name = group["rows"][0][0]
        baseline = float(
            (benchmarks.get(baseline_name, {}).get("result") or {}).get(stat_key) or 0.0
        )
        cells = []
        for name, _, series in group["rows"]:
            result = (benchmarks.get(name) or {}).get("result") or {}
            median = float(result.get(stat_key) or 0.0)
            if not median:
                cells.append("-")
                continue
            value_text = format(median * UNIT_SCALE[unit], ",.1f") + " " + unit
            if series == "sync" or not baseline:
                cells.append(value_text)
            else:
                ratio = median / baseline
                ratio_text = (
                    format(ratio, ".1f") if ratio < 10 else format(ratio, ",.0f")
                ) + "x"
                cells.append(value_text + " (" + ratio_text + ")")
        table.add_row(group["metric"], *cells)

    Console().print(table)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_suite(quick: bool = False) -> int:
    results_dir = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    # Remove results from previous runs so nothing stale leaks into the summary
    for stale in results_dir.glob("*.json"):
        stale.unlink()

    env = dict(os.environ)
    env["AGNO_BENCH_RESULTS_DIR"] = str(results_dir)
    env["AGNO_BENCH_QUIET"] = "1"
    env["AGNO_TELEMETRY"] = "false"
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "placeholder-not-used")
    env["OTEL_SDK_DISABLED"] = "true"
    env["CREWAI_TELEMETRY_OPT_OUT"] = "true"
    env["CREWAI_DISABLE_TELEMETRY"] = "true"
    if quick:
        env["AGNO_BENCH_ITERATIONS"] = "5"

    failures = []
    for file_name in BENCHMARK_FILES:
        print("", flush=True)
        print(">>> " + file_name, flush=True)
        start = perf_counter()
        proc = subprocess.run(
            [sys.executable, str(SUITE_DIR / file_name)],
            env=env,
            cwd=str(SUITE_DIR),
        )
        elapsed = perf_counter() - start
        if proc.returncode != 0:
            failures.append(file_name)
            print(
                "FAILED: " + file_name + " (exit " + str(proc.returncode) + ")",
                flush=True,
            )
        else:
            print("done in " + format(elapsed, ".1f") + " s", flush=True)

    benchmarks = {}
    for result_file in sorted(results_dir.glob("*.json")):
        if result_file.name == "summary.json":
            continue
        payload = json.loads(result_file.read_text())
        benchmarks[payload["name"]] = payload

    summary = {
        "machine": get_machine_info(),
        "framework_versions": framework_versions(),
        "quick": quick,
        "failures": failures,
        "benchmarks": benchmarks,
    }
    summary_path = results_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print("", flush=True)
    print_agno_vs_table(benchmarks, summary["framework_versions"])
    print("", flush=True)
    print_summary_table(
        benchmarks,
        machine=summary["machine"],
        title="Cross-Framework Benchmark Summary",
    )
    print("", flush=True)
    print("Summary written to " + str(summary_path), flush=True)

    if failures:
        print("Failed benchmarks: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_suite(quick="--quick" in sys.argv))
