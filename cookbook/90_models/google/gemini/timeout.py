"""
Gemini Timeout
==============

Set a request timeout (in seconds) for the Gemini model.
The timeout is converted to milliseconds and passed via http_options
to the underlying genai.Client.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent with timeout
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-2.5-flash", timeout=30.0),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
