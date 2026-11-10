"""
Agno Instantiation Comparison Benchmark
=======================================

Creates an Agno Agent with an OpenAI model reference and one function tool:
the same shape every framework in this folder is measured with.
"""

from _compare import iterations, run_benchmarks
from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIResponses


# ---------------------------------------------------------------------------
# Benchmark Tool
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny in " + city


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def agno_instantiation():
    return Agent(
        model=OpenAIResponses(id="gpt-5.5"), tools=[get_weather], telemetry=False
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
agno_instantiation_perf = PerformanceEval(
    name="agno_instantiation",
    func=agno_instantiation,
    num_iterations=iterations(1000),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([agno_instantiation_perf], group="comparison")
