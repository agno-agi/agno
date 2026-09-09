"""
Cold Import Time Benchmark
==========================

Measures how long a fresh Python process takes to import agno, on top of
bare interpreter startup. Import time is paid once per process, so it
dominates CLI tools, serverless cold starts and short-lived workers.

Each sample is a fresh subprocess; the reported number is the import
statement's cost with interpreter startup subtracted. An importtime
profile of the heaviest modules is saved alongside the stats.
"""

import statistics
import subprocess
import sys
from time import perf_counter

from _bench import iterations, save_result
from agno.eval.performance import PerformanceResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IMPORT_TARGETS = {
    "import_agno": "import agno",
    "import_agno_agent": "from agno.agent import Agent",
}
SAMPLES = iterations(15)


# ---------------------------------------------------------------------------
# Measurement Helpers
# ---------------------------------------------------------------------------
def time_subprocess(code: str) -> float:
    """Wall time of one fresh interpreter running the given code."""
    start = perf_counter()
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    elapsed = perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(
            "Import failed for " + repr(code) + ":\n" + proc.stderr.strip()[-2000:]
        )
    return elapsed


def measure(code: str, samples: int) -> list:
    return [time_subprocess(code) for _ in range(samples)]


def importtime_profile(code: str, top_n: int = 25) -> list:
    """Top self-time offenders from python -X importtime, as (self_us, module) rows."""
    out = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", code],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(
            "Import failed for " + repr(code) + ":\n" + out.stderr.strip()[-2000:]
        )
    rows = []
    for line in out.stderr.splitlines():
        # Format: "import time: <self us> | <cumulative us> | <indented module>"
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        try:
            self_us = int(parts[0].split(":")[1].strip())
        except ValueError:
            continue
        rows.append(
            {
                "self_us": self_us,
                "cumulative_us": int(parts[1].strip()),
                "module": parts[2].strip(),
            }
        )
    rows.sort(key=lambda r: r["self_us"], reverse=True)
    return rows[:top_n]


# ---------------------------------------------------------------------------
# Run Benchmark
# ---------------------------------------------------------------------------
def main():
    # Interpreter startup baseline, subtracted from every import measurement
    baseline_samples = measure("pass", SAMPLES)
    baseline = statistics.median(baseline_samples)
    print("Interpreter startup median: " + format(baseline * 1000, ".1f") + " ms")

    for name, code in IMPORT_TARGETS.items():
        samples = measure(code, SAMPLES)
        adjusted = [max(0.0, s - baseline) for s in samples]
        result = PerformanceResult(run_id=name, run_times=adjusted, memory_usages=[])
        print(
            name
            + ": median "
            + format(result.median_run_time * 1000, ".1f")
            + " ms | p95 "
            + format(result.p95_run_time * 1000, ".1f")
            + " ms (interpreter startup subtracted)"
        )
        save_result(
            name=name,
            group="import",
            result=result,
            num_iterations=SAMPLES,
            warmup_runs=0,
            extra={
                "interpreter_startup_median_s": baseline,
                "importtime_top": importtime_profile(code),
            },
        )


if __name__ == "__main__":
    main()
