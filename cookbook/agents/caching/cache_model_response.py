"""
Example showing how to cache model responses to avoid redundant API calls.

The first run will take a while to finish.
The second run will hit the cache and be much faster.

You can also see the cache hit log in the console logs.
"""

import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o", cache_response=True))

# Run the same query twice to demonstrate caching
for i in range(1, 3):
    print(f"\n{'=' * 60}")
    print(
        f"Run {i}: {'Cache Miss (First Request)' if i == 1 else 'Cache Hit (Cached Response)'}"
    )
    print(f"{'=' * 60}\n")

    response = agent.run(
        "Write me a short story about a cat that can talk and solve problems."
    )
    print(response.content)
    print(f"\n Elapsed time: {response.metrics.duration:.3f}s")

    # Small delay between iterations for clarity
    if i == 1:
        time.sleep(0.5)
