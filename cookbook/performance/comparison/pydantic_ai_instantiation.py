"""
PydanticAI Instantiation Comparison Benchmark
=============================================

Creates a PydanticAI Agent with an OpenAI model reference and one tool,
the same shape every framework in this folder is measured with.
"""

from _compare import iterations, run_benchmarks
from agno.eval.performance import PerformanceEval
from pydantic_ai import Agent


# ---------------------------------------------------------------------------
# Benchmark Tool
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny in " + city


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def pydantic_ai_instantiation():
    return Agent("openai:gpt-5.5", tools=[get_weather])


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
pydantic_ai_instantiation_perf = PerformanceEval(
    name="pydantic_ai_instantiation",
    func=pydantic_ai_instantiation,
    num_iterations=iterations(100),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([pydantic_ai_instantiation_perf], group="comparison")
