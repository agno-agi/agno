"""This example shows how to run a Performance evaluation on an async function."""

import asyncio

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# Simple async function to run an Agent.
async def arun_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        system_message="Be concise, reply with one sentence.",
    )
    response = await agent.arun("What is the capital of France?")
    return response


performance_eval = PerformanceEval(func=arun_agent, num_iterations=10)

# Because we are evaluating an async function, we use the arun method.
asyncio.run(performance_eval.arun(print_summary=True, print_results=True))
