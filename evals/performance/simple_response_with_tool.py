"""Run `pip install agno openai memory_profiler` to install dependencies."""

from typing import Literal

from agno.agent import Agent
from agno.memory.agent import AgentMemory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.eval.perf import PerfEval

def get_weather(city: Literal["nyc", "sf"]):
    """
    Use this to get weather information.
    Args:
        city: The city to get the weather for. Valid values are "nyc" and "sf".
    Returns:
        The weather in the city.
    """
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"

def simple_response():
    agent = Agent(model=OpenAIChat(id='gpt-4o'), 
                add_history_to_messages=True,
                user_id="john_billings",
                system_message='Be concise, reply with one sentence.',
                tools=[get_weather])
    response = agent.run('What is the weather in New York?')
    return response

simple_response_perf = PerfEval(func=simple_response, num_iterations=10)


if __name__ == "__main__":
    simple_response_perf.run(print_results=True)
