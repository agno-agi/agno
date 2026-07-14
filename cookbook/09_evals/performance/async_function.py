"""
Async Function Performance Evaluation
=====================================

Demonstrates performance evaluation for an asynchronous function.
"""

import asyncio

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
async def arun_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        system_message="Be concise, reply with one sentence.",
    )
    response = await agent.arun("What is the capital of France?")
    return response


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
performance_eval = PerformanceEval(func=arun_agent, num_iterations=10)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(performance_eval.arun(print_summary=True, print_results=True))
