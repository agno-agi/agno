"""
Web Context Provider with Parallel
==================================

`ParallelBackend` speaks directly to Parallel's beta web API via the
`parallel-web` SDK. Two tools: `web_search(objective)` returns
URL + excerpt pairs for a natural-language objective; `web_extract(url)`
fetches full-page content.

Pick this over Exa when you want Parallel's search ranking, excerpt
shape, or pricing.

Requires:
    OPENAI_API_KEY
    PARALLEL_API_KEY   (https://platform.parallel.ai/)
    pip install parallel-web
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.web import ParallelBackend, WebContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
backend = ParallelBackend()  # reads PARALLEL_API_KEY from env
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
