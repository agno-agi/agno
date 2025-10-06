"""Run `pip install agno openai memory_profiler` to install dependencies."""

from typing import Literal

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"


tools = [get_weather]


def instantiate_agent():
    return Agent(model=OpenAIChat(id="gpt-4o"), tools=tools)  # type: ignore


instantiation_perf = PerformanceEval(
    name="Agent Instantiation", func=instantiate_agent, num_iterations=1000
)

if __name__ == "__main__":
    instantiation_perf.run(print_results=True, print_summary=True)
