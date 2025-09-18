"""Run `pip install autogen-agentchat "autogen-ext[openai]"` to install dependencies."""

from typing import Literal

from agno.eval.performance import PerformanceEval
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient


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
    return AssistantAgent(
        name="assistant",
        model_client=OpenAIChatCompletionClient(
            model="gpt-4o",
            model_info={
                "vision": False,
                "function_calling": True,
                "json_output": False,
                "family": "gpt-4o",
                "structured_output": True,
            },
        ),
        tools=tools,
    )


autogen_instantiation = PerformanceEval(func=instantiate_agent, num_iterations=1000)

if __name__ == "__main__":
    autogen_instantiation.run(print_results=True, print_summary=True)
