"""
Web Context Provider with Exa
=============================

WebContextProvider wraps a `ContextBackend` so the provider interface
doesn't know about the search/fetch implementation. Here we use
`ExaBackend` (Exa's search + contents API).

Requires:
    OPENAI_API_KEY
    EXA_API_KEY  (https://dashboard.exa.ai/)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.web import ExaBackend, WebContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
backend = ExaBackend()  # reads EXA_API_KEY from env
web = WebContextProvider(backend=backend, model=OpenAIResponses(id="gpt-5.4-mini"))

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=web.get_tools(),
    instructions=web.instructions() + "\nAlways cite URLs inline.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nweb.status() = {web.status()}\n")
    prompt = "What is the latest stable release of CPython? Cite the source."
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
