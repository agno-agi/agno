"""Run `pip install openai pydantic-ai` to install dependencies."""
from typing import Literal

from pydantic_ai import Agent
from agno.eval.perf import PerfEval


def instantiate_agent():
    agent =  Agent('openai:gpt-4o', system_prompt='Be concise, reply with one sentence.')

    @agent.tool_plain
    def get_weather(city: Literal["nyc", "sf"]):
        """Use this to get weather information."""
        if city == "nyc":
            return "It might be cloudy in nyc"
        elif city == "sf":
            return "It's always sunny in sf"
        else:
            raise AssertionError("Unknown city")

    return agent

pydantic_instantiation = PerfEval(func=instantiate_agent, num_iterations=1000)

if __name__ == "__main__":
    pydantic_instantiation.run(print_results=True)
