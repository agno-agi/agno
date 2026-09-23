"""
Cheaper Inference Tool Use
==========================

Cookbook example for `cheaperinference/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.cheaperinference import CheaperInference
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=CheaperInference(id="gpt-5.4"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("What is happening in France?", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("What is happening in France?"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("What is happening in France?", stream=True))
