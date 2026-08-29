"""
CrewAI Instantiation Comparison Benchmark
=========================================

Creates a CrewAI Agent with an OpenAI model reference and one tool,
the same shape every framework in this folder is measured with.
"""

from _compare import iterations, run_benchmarks
from agno.eval.performance import PerformanceEval
from crewai import Agent
from crewai.tools import tool


# ---------------------------------------------------------------------------
# Benchmark Tool
# ---------------------------------------------------------------------------
@tool("get_weather")
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny in " + city


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def crewai_instantiation():
    return Agent(
        role="Assistant",
        goal="Answer questions",
        backstory="A helpful assistant",
        tools=[get_weather],
        llm="gpt-5.5",
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
crewai_instantiation_perf = PerformanceEval(
    name="crewai_instantiation",
    func=crewai_instantiation,
    num_iterations=iterations(100),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([crewai_instantiation_perf], group="comparison")
