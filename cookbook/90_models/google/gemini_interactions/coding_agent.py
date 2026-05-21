"""
Gemini Interactions - Basic
============================

Basic example using the Gemini Interactions API.

The Interactions API provides server-side conversation history management,
so only new messages are sent each turn instead of the full history.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Can you tell me about Agno? And look at the open PRs ")
