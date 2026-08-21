"""
Benchmark Suite Runner
======================

Runs every benchmark in this folder sequentially, each in a fresh Python
process so no benchmark inherits another's warmed caches or allocator
state. Collects the per-benchmark JSON files plus machine information
into results/summary.json, ready for report.py.

Usage:
    python cookbook/performance/run_all.py            # agno suite
    python cookbook/performance/run_all.py --all      # + cross-framework comparison + HTML report
    python cookbook/performance/run_all.py --quick    # smoke run, few iterations (composes with --all)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from _bench import get_machine_info, print_summary_table

# ---------------------------------------------------------------------------
# Configuration: benchmarks run in this order, one process at a time
# ---------------------------------------------------------------------------
BENCHMARK_FILES = [
    "import_time.py",
    "instantiate_agent.py",
    "instantiate_agent_with_tools.py",
    "instantiate_team.py",
    "instantiate_workflow.py",
    "run_agent.py",
    "run_agent_streaming.py",
    "run_agent_with_tools.py",
    "run_agent_with_storage.py",
    "memory_footprint.py",
]

SUITE_DIR = Path(__file__).parent
RESULTS_DIR = SUITE_DIR / "results"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_suite(quick: bool = False) -> int:
    # Quick runs get their own directory so a smoke run never clobbers or
    # masquerades as a full baseline.
    results_dir = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    # Remove results from previous runs: leftover files for a renamed or
    # failing benchmark would otherwise leak into the new summary.
    for stale in results_dir.glob("*.json"):
        stale.unlink()

    env = dict(os.environ)
    env["AGNO_BENCH_RESULTS_DIR"] = str(results_dir)
    env["AGNO_BENCH_QUIET"] = "1"
    env["AGNO_TELEMETRY"] = "false"
    if quick:
        env["AGNO_BENCH_ITERATIONS"] = "5"

    failures = []
    for file_name in BENCHMARK_FILES:
        # Flush before handing the terminal to the child, or the runner's
        # header lands after the child's output in piped logs
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

    # Collect per-benchmark results into one summary
    benchmarks = {}
    for result_file in sorted(results_dir.glob("*.json")):
        if result_file.name == "summary.json":
            continue
        payload = json.loads(result_file.read_text())
        benchmarks[payload["name"]] = payload

    summary = {
        "machine": get_machine_info(),
        "quick": quick,
        "failures": failures,
        "benchmarks": benchmarks,
    }
    summary_path = results_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print("")
    print_summary_table(
        benchmarks, machine=summary["machine"], title="Agno Benchmark Summary"
    )
    print("")
    print("Summary written to " + str(summary_path))

    if failures:
        print("Failed benchmarks: " + ", ".join(failures))
        return 1
    return 0


# ---------------------------------------------------------------------------
# Everything Mode: agno suite + cross-framework comparison + HTML report
# ---------------------------------------------------------------------------
def comparison_frameworks_available() -> bool:
    probe = subprocess.run(
        [sys.executable, "-c", "import langgraph, pydantic_ai, crewai"],
        capture_output=True,
    )
    return probe.returncode == 0


def run_everything(quick: bool = False) -> int:
    exit_code = run_suite(quick=quick)

    if comparison_frameworks_available():
        print("", flush=True)
        print(">>> cross-framework comparison", flush=True)
        proc = subprocess.run(
            [sys.executable, str(SUITE_DIR / "comparison" / "run_all.py")]
            + (["--quick"] if quick else [])
        )
        exit_code = exit_code or proc.returncode
    else:
        print("", flush=True)
        print(
            "Comparison frameworks not installed - skipping the cross-framework suite."
        )
        print("Create the full environment with: ./scripts/perf_setup.sh")

    # Render whatever this invocation produced (quick output stays isolated)
    results_root = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    comparison_root = (
        RESULTS_DIR / "comparison" / "quick" if quick else RESULTS_DIR / "comparison"
    )
    results_path = results_root / "summary.json"
    comparison_path = comparison_root / "summary.json"
    report_path = (
        SUITE_DIR
        / "report"
        / ("agno-performance-quick.html" if quick else "agno-performance.html")
    )
    report_cmd = [
        sys.executable,
        str(SUITE_DIR / "report.py"),
        "--results",
        str(results_path),
        "--comparison",
        str(comparison_path),
        "--out",
        str(report_path),
    ]
    print("", flush=True)
    proc = subprocess.run(report_cmd)
    exit_code = exit_code or proc.returncode
    return exit_code


if __name__ == "__main__":
    if "--all" in sys.argv:
        sys.exit(run_everything(quick="--quick" in sys.argv))
    sys.exit(run_suite(quick="--quick" in sys.argv))
