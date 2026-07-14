"""
DaoXE Tool Use
==============

Cookbook example for `daoxe/tool_use.py`.
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.daoxe import DaoXE
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

model_id = os.environ.get("DAOXE_MODEL")
if not model_id:
    raise SystemExit(
        "Set DAOXE_MODEL to an exact model ID from your DaoXE account catalog "
        "(GET /v1/models)."
    )

agent = Agent(
    model=DaoXE(id=model_id),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Whats happening in France?"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
