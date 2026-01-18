"""
Example showing async caching for streaming model responses.

The first run will take a while to finish.
The second run will hit the cache and be much faster.

You can also see the cache hit log in the console logs.
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o", cache_response=True))


async def main():
    # Run the same query twice to demonstrate caching
    for i in range(1, 3):
        print(f"\n{'=' * 60}")
        print(
            f"Run {i}: {'Cache Miss (First Request)' if i == 1 else 'Cache Hit (Cached Response)'}"
        )
        print(f"{'=' * 60}\n")

        start_time = time.time()
        await agent.aprint_response(
            "Write me a short story about a cat that can talk and solve problems.",
            stream=True,
        )
        elapsed_time = time.time() - start_time

        print()  # New line after streaming
        print(f"\n Elapsed time: {elapsed_time:.3f}s")

        # Small delay between iterations for clarity
        if i == 1:
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
