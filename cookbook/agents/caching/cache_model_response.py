"""
Example showing how to cache model responses to avoid redundant API calls.

This cookbook runs the same query twice in a single execution to demonstrate:
- First run: Cache MISS (slower, makes actual API call)
- Second run: Cache HIT (instant, replays from cache)

Check the console logs and timing to see the performance difference.
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

    start_time = time.time()
    agent.print_response(
        "Write me a short story about a cat that can talk and solve problems."
    )
    elapsed_time = time.time() - start_time

    print(f"\n Elapsed time: {elapsed_time:.2f}s")

    # Small delay between iterations for clarity
    if i == 1:
        time.sleep(0.5)
