"""Concurrent Agent Execution with asyncio.gather

Demonstrates how to run multiple agent tasks concurrently using asyncio.gather.
This pattern is useful when you need to execute multiple independent tasks in parallel.

Note: The agent is created ONCE and reused for all tasks. Creating agents in loops
is an anti-pattern that wastes resources.

Requirements:
- OPENAI_API_KEY environment variable
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from rich.pretty import pprint

providers = ["openai", "anthropic", "ollama", "cohere", "google"]
instructions = [
    "Your task is to write a well researched report on AI providers.",
    "The report should be unbiased and factual.",
]

# Create the agent ONCE outside the loop - this is the correct pattern
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    tools=[DuckDuckGoTools()],
)


async def get_reports():
    """Run multiple research tasks concurrently using the same agent instance."""
    tasks = [
        agent.arun(f"Write a report on the following AI provider: {provider}")
        for provider in providers
    ]
    results = await asyncio.gather(*tasks)
    return results


async def main():
    results = await get_reports()
    for result in results:
        print("************")
        pprint(result.content)
        print("************")
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
