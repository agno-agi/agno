"""Async CriteriaEval as post-hook example."""

import asyncio

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval
from agno.models.openai import OpenAIChat


async def main():
    criteria_eval = CriteriaEval(
        name="Response Quality Check",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be professional and accurate",
        threshold=7,
        print_results=True,
        print_summary=True,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        instructions="Provide professional and accurate answers.",
        post_hooks=[criteria_eval],
    )

    response = await agent.arun("What are the benefits of renewable energy?")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
