"""
Gemini 4 Argon
==============

Use `gemini-4-argon` with web search tools in sync, async, and streaming modes.

Run `uv pip install -U google-genai ddgs agno` to install dependencies.
Export `GOOGLE_API_KEY` before running.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-4-argon"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prompt = (
        "Search for the latest developments in AI agents and summarize the top three."
    )

    # --- Sync ---
    agent.print_response(prompt)

    # --- Sync + Streaming ---
    agent.print_response(prompt, stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response(prompt))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response(prompt, stream=True))
