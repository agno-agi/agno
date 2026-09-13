"""
Memory Footprint Benchmark
==========================

Measures the resident memory cost of holding many live Agents, not the
transient allocation peak of creating one. Each sample creates a batch of
agents, keeps them alive, and reports tracemalloc's net allocation delta
divided by the batch size: the true per-agent footprint at scale.
"""

import gc
import tracemalloc

from _bench import add_numbers, get_weather, iterations, save_result
from agno.agent import Agent
from agno.eval.performance import PerformanceResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AGENTS_PER_SAMPLE = 1000
# The iteration override caps sample count, but this benchmark never needs many samples
SAMPLES = min(iterations(5), 10)


# ---------------------------------------------------------------------------
# Agent Factories
# ---------------------------------------------------------------------------
def bare_agent():
    return Agent(system_message="Be concise, reply with one sentence.", telemetry=False)


def tooled_agent():
    return Agent(
        system_message="Be concise, reply with one sentence.",
        tools=[add_numbers, get_weather],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Measurement Helper
# ---------------------------------------------------------------------------
def per_agent_footprint(factory) -> float:
    """Net MiB per live agent for a batch of AGENTS_PER_SAMPLE agents."""
    gc.collect()
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    agents = [factory() for _ in range(AGENTS_PER_SAMPLE)]
    gc.collect()
    after, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del agents
    gc.collect()
    return max(0.0, (after - before) / 1024 / 1024 / AGENTS_PER_SAMPLE)


# ---------------------------------------------------------------------------
# Run Benchmark
# ---------------------------------------------------------------------------
def main():
    for name, factory in [
        ("memory_per_agent", bare_agent),
        ("memory_per_agent_with_tools", tooled_agent),
    ]:
        usages = [per_agent_footprint(factory) for _ in range(SAMPLES)]
        result = PerformanceResult(run_id=name, run_times=[], memory_usages=usages)
        print(
            name
            + ": median "
            + format(result.median_memory_usage * 1024, ".2f")
            + " KiB per live agent ("
            + str(AGENTS_PER_SAMPLE)
            + " agents per sample, "
            + str(SAMPLES)
            + " samples)"
        )
        save_result(
            name=name,
            group="memory",
            result=result,
            num_iterations=SAMPLES,
            warmup_runs=0,
            extra={"agents_per_sample": AGENTS_PER_SAMPLE},
        )


if __name__ == "__main__":
    main()
