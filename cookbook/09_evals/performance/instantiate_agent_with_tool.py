"""
Agent-with-Tool Instantiation Performance Evaluation
====================================================

Demonstrates measuring instantiation performance for a tooled agent.
"""

from typing import Literal

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Create Benchmark Tool
# ---------------------------------------------------------------------------
def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"


tools = [get_weather]


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent():
    return Agent(model=OpenAIChat(id="gpt-4o"), tools=tools)  # type: ignore


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
instantiation_perf = PerformanceEval(
    name="Agent Instantiation", func=instantiate_agent, num_iterations=1000
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    instantiation_perf.run(print_results=True, print_summary=True)
