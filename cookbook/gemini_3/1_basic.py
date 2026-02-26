"""
1. Basic Agent
==============
The simplest Agno agent. A Gemini model and a prompt -- nothing else.
No tools, no memory, no persistence. This is your starting point.

Run:
    python cookbook/gemini_3/1_basic.py

Example prompt:
    "What are the top 3 things to see in Paris?"
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
chat_agent = Agent(
    name="Chat Assistant",
    model=Gemini(id="gemini-3-flash-preview"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    chat_agent.print_response("What are the top 3 things to see in Paris?")

    # --- Sync + Streaming ---
    chat_agent.print_response(
        "What are the top 3 things to see in Paris?", stream=True
    )

    # --- Async ---
    asyncio.run(
        chat_agent.aprint_response("What are the top 3 things to see in Paris?")
    )

    # --- Async + Streaming ---
    asyncio.run(
        chat_agent.aprint_response(
            "What are the top 3 things to see in Paris?", stream=True
        )
    )
