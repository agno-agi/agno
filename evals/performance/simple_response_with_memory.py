"""Run `pip install agno openai memory_profiler` to install dependencies."""

from typing import Literal

from agno.agent import Agent
from agno.memory.agent import AgentMemory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.eval.perf import PerfEval

def simple_response():
    agent = Agent(
        model=OpenAIChat(id='gpt-4o'), 
        add_history_to_messages=True,
        context={"memory": "The user's name is John Billings."},
        add_context=True,
        system_message='Be concise, reply with one sentence.',
    )
    response = agent.run('What is my name?')
    print(response.content)
    return response

simple_response_perf = PerfEval(func=simple_response, num_iterations=10)


if __name__ == "__main__":
    simple_response_perf.run(print_results=True)
