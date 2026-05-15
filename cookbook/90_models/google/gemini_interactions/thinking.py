"""
Gemini Interactions - Thinking
===============================

Example showing thinking/reasoning with the Gemini Interactions API.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(
        id="gemini-3-flash-preview",
        thinking_level="high",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "Solve: If a train travels at 60 mph for 2.5 hours, then at 80 mph for 1.5 hours, what is the total distance and average speed?"
    )

    # --- Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Explain why the sum of angles in a triangle is always 180 degrees.",
            stream=True,
        )
    )
