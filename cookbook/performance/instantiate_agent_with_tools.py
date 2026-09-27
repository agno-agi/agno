"""
Tooled Agent Instantiation Benchmark
====================================

Measures the cost of creating an Agent with five function tools.
Agent construction stores the tool list without processing it: schema
extraction is deferred to the first run, so this should stay close to the
bare agent benchmark. This benchmark pins that deferral; the deferred cost
itself shows up in the tool-call run benchmark.
"""

from _bench import (
    add_numbers,
    get_news,
    get_time,
    get_weather,
    iterations,
    multiply_numbers,
    run_benchmarks,
)
from agno.agent import Agent
from agno.eval.performance import PerformanceEval


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent_with_tools():
    return Agent(
        system_message="Be concise, reply with one sentence.",
        tools=[add_numbers, multiply_numbers, get_weather, get_time, get_news],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
instantiate_agent_with_tools_perf = PerformanceEval(
    name="instantiate_agent_with_tools",
    func=instantiate_agent_with_tools,
    num_iterations=iterations(1000),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([instantiate_agent_with_tools_perf], group="instantiation")
