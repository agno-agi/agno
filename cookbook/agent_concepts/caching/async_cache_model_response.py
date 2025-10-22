"""
Example showing async caching for model responses.

Run this cookbook twice to see the difference in response time.

The first time should take a while to run.
The second time should be instant.
You can also see in the console about the cache hit/miss status
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o", cache_response=True), debug_mode=True
)


async def main():
    # Should take a while to run the first time, then replay from cache
    response = await agent.arun(
        "Write me a very very short and sweet story about a cat that can talk and solve problems."
    )
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
