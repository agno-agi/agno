"""
Web Context Provider with AnySearch
===================================

AnySearchBackend speaks to AnySearch's REST API (https://www.anysearch.com).
Four tools: web_search(query) returns URL + title + excerpt for each result,
web_search_batch(queries) runs up to five searches in one call,
web_extract(url) fetches full-page content, and web_sub_domains(domains) lists
the vertical tags a search can target.

No API key is required: anonymous traffic is rate-limited per client IP and
metered against AnySearch's daily free quota. ANYSEARCH_API_KEY bills against
the paid quota, which comes with higher concurrency limits.

Requires:
    OPENAI_API_KEY
    ANYSEARCH_API_KEY   (optional)

Any model works for both the calling agent and the provider's sub-agent: swap
OpenAIResponses for your own provider - for example DeepSeek(id="deepseek-flash")
with DEEPSEEK_API_KEY set.
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.web import AnySearchBackend, WebContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
backend = AnySearchBackend()  # reads ANYSEARCH_API_KEY from env when it is set
web = WebContextProvider(backend=backend, model=OpenAIResponses(id="gpt-5.6-luna"))

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
