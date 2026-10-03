"""
Team Instantiation Benchmark
============================

Measures the cost of creating a Team wrapping three member Agents.
Members are created inside the benchmark function on purpose: the
measurement is the full cost of standing up a fresh team.
"""

from _bench import iterations, run_benchmarks
from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.team import Team


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_team():
    return Team(
        name="benchmark-team",
        members=[
            Agent(name="researcher", telemetry=False),
            Agent(name="writer", telemetry=False),
            Agent(name="reviewer", telemetry=False),
        ],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
instantiate_team_perf = PerformanceEval(
    name="instantiate_team",
    func=instantiate_team,
    num_iterations=iterations(1000),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([instantiate_team_perf], group="instantiation")
