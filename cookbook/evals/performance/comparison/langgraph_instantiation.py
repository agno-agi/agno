"""Run `pip install langgraph langchain_openai` to install dependencies."""

from typing import Literal

from agno.eval.performance import PerformanceEval
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


@tool
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
    return create_react_agent(model=ChatOpenAI(model="gpt-4o"), tools=tools)


langgraph_instantiation = PerformanceEval(func=instantiate_agent, num_iterations=1000)

if __name__ == "__main__":
    langgraph_instantiation.run(print_results=True, print_summary=True)
