"""
LangGraph Instantiation Comparison Benchmark
============================================

Creates a LangGraph react agent with an OpenAI model reference and one tool.
create_react_agent compiles a state graph per call, which is the dominant
cost. LangGraph 1.x deprecates this entrypoint in favor of the langchain
package's create_agent; it remains the canonical langgraph-only API.
"""

import warnings

from _compare import iterations, run_benchmarks
from agno.eval.performance import PerformanceEval

warnings.filterwarnings("ignore", category=DeprecationWarning)

from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402


# ---------------------------------------------------------------------------
# Benchmark Tool
# ---------------------------------------------------------------------------
@tool
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny in " + city


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def langgraph_instantiation():
    return create_react_agent(model=ChatOpenAI(model="gpt-5.5"), tools=[get_weather])


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
langgraph_instantiation_perf = PerformanceEval(
    name="langgraph_instantiation",
    func=langgraph_instantiation,
    num_iterations=iterations(300),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([langgraph_instantiation_perf], group="comparison")
