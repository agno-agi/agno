"""
Gemini 3.8 Flash
================

Basic cookbook example for `gemini-3.8-flash`, using tools.

Run `uv pip install -U google-genai ddgs agno` to install dependencies.
Export `GOOGLE_API_KEY` before running.
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3.8-flash"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("What are the latest developments in AI agents?")
# print(run.content)

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
