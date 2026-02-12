"""
Concurrent Execution
=============================

Concurrent Agent Execution with asyncio.gather.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
providers = ["openai", "anthropic", "ollama", "cohere", "google"]
instructions = """
Your task is to write a well researched report on AI providers.
The report should be unbiased and factual.
"""

# Create the agent ONCE outside the loop - this is the correct pattern
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
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


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
