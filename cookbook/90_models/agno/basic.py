"""
Agno Gateway (basic)
====================

Use any model through the Agno gateway with a single Agno API key. The class talks
to the gateway over httpx using the OpenAI chat-completions schema, so it needs no
provider SDK installed. The gateway routes to every provider by the model id prefix
and bills through your Agno account.

Address models as ``<provider>/<model>``:
    Agno(id="openai/gpt-5.4")
    Agno(id="google/gemini-3-flash")

Anthropic support is planned via the messages endpoint; ``anthropic/*`` ids raise a
clear error for now.

Requires:
- AGNO_API_KEY

Set ``AGNO_API_KEY`` in your shell before running (see README), not in this file.
"""

import asyncio

from agno.agent import Agent
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
