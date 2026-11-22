"""
Cold Import Comparison Benchmark
================================

Measures each framework's cold import in a fresh Python process,
interpreter startup subtracted: the cost of getting to a usable Agent
class. Paid once per process, so it dominates CLI tools and serverless
cold starts.
"""

import statistics

from _compare import iterations, save_result
from agno.eval.performance import PerformanceResult
from import_time import measure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IMPORT_TARGETS = {
    "import_compare_agno": "from agno.agent import Agent",
    "import_compare_langgraph": "from langgraph.prebuilt import create_react_agent",
    "import_compare_pydantic_ai": "from pydantic_ai import Agent",
    "import_compare_crewai": "from crewai import Agent",
}
SAMPLES = iterations(10)


# ---------------------------------------------------------------------------
# Run Benchmark
# ---------------------------------------------------------------------------
def main():
    baseline_samples = measure("pass", SAMPLES)
    baseline = statistics.median(baseline_samples)
    print("Interpreter startup median: " + format(baseline * 1000, ".1f") + " ms")

    for name, code in IMPORT_TARGETS.items():
        samples = measure(code, SAMPLES)
        adjusted = [max(0.0, s - baseline) for s in samples]
        result = PerformanceResult(run_id=name, run_times=adjusted, memory_usages=[])
        print(name + ": median " + format(result.median_run_time * 1000, ".1f") + " ms")
        save_result(
            name=name,
            group="comparison_import",
            result=result,
            num_iterations=SAMPLES,
            warmup_runs=0,
            extra={"interpreter_startup_median_s": baseline, "import_statement": code},
        )


if __name__ == "__main__":
    main()
