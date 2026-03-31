"""
OpenAI Agents Instantiation Performance Evaluation
==================================================

Demonstrates agent instantiation benchmarking with OpenAI Agents SDK.
"""

from typing import Literal

from agno.eval.performance import PerformanceEval

try:
    from agents import Agent, function_tool
except ImportError:
    raise ImportError(
        "OpenAI agents not installed. Please install it using `uv pip install openai-agents`."
    )


# ---------------------------------------------------------------------------
# Create Benchmark Tool
# ---------------------------------------------------------------------------
def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"
    else:
        raise AssertionError("Unknown city")


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent():
    return Agent(
        name="Haiku agent",
        instructions="Always respond in haiku form",
        model="o3-mini",
        tools=[function_tool(get_weather)],
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
openai_agents_instantiation = PerformanceEval(
    func=instantiate_agent, num_iterations=1000
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    openai_agents_instantiation.run(print_results=True, print_summary=True)
