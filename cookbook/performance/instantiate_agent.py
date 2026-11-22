"""
Agent Instantiation Benchmark
=============================

Measures the time and memory cost of creating a bare Agent.
This is the floor for any Agno application: it should stay in the
microsecond / few-KiB range.
"""

from _bench import iterations, run_benchmarks
from agno.agent import Agent
from agno.eval.performance import PerformanceEval


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent():
    return Agent(system_message="Be concise, reply with one sentence.", telemetry=False)


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
instantiate_agent_perf = PerformanceEval(
    name="instantiate_agent",
    func=instantiate_agent,
    num_iterations=iterations(1000),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([instantiate_agent_perf], group="instantiation")
