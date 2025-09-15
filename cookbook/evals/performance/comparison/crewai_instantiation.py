"""Run `pip install openai crewai` to install dependencies."""

from typing import Literal

from agno.eval.performance import PerformanceEval
from crewai.agent import Agent
from crewai.tools import tool


@tool("Tool Name")
def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"
    else:
        raise AssertionError("Unknown city")


tools = [get_weather]


def instantiate_agent():
    return Agent(
        llm="gpt-4o",
        role="Test Agent",
        goal="Be concise, reply with one sentence.",
        tools=tools,
        backstory="Test",
    )


crew_instantiation = PerformanceEval(func=instantiate_agent, num_iterations=1000)

if __name__ == "__main__":
    crew_instantiation.run(print_results=True, print_summary=True)
