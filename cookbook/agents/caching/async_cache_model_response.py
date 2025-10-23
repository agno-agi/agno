"""
Example showing async caching for model responses.

The first run will take a while to finish.
The second run will hit the cache and be much faster.

You can also see the cache hit announcement in the console logs.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o", cache_response=True))


async def main():
    res = await agent.arun(
        "Write me a brief story about a cat that can talk and solve problems."
    )
    print(f"First run (no cache used) took: {res.metrics.duration:.3f} seconds")  # type: ignore

    second_res = await agent.arun(
        "Write me a brief story about a cat that can talk and solve problems."
    )
    print(f"Second run (cache used) took: {second_res.metrics.duration:.3f} seconds")  # type: ignore


if __name__ == "__main__":
    asyncio.run(main())
