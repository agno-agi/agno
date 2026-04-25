"""
Cache Model Response
=============================

Example showing how to cache model responses to avoid redundant API calls.
"""

import time

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(model=OpenAIResponses(id="gpt-4o", cache_response=True))

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
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
