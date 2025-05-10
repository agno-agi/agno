"""Run `pip install agents` to install dependencies."""

from typing import Literal

from agents import Agent, function_tool
from agno.eval.performance import PerformanceEval


def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"
    else:
        raise AssertionError("Unknown city")


def instantiate_agent():
    return Agent(
        name="Haiku agent",
        instructions="Always respond in haiku form",
        model="o3-mini",
        tools=[function_tool(get_weather)],
    )


openai_agents_instantiation = PerformanceEval(
    func=instantiate_agent, num_iterations=1000
)

if __name__ == "__main__":
    openai_agents_instantiation.run(print_results=True, print_summary=True)
