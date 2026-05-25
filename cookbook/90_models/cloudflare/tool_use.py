"""
Cloudflare AI Gateway — tool use
================================

Runs a Workers AI chat model through Cloudflare AI Gateway's OpenAI-compatible
``/compat`` endpoint with a tool. The OpenAI ``tools`` / ``tool_calls`` schema
is forwarded as-is by the gateway; the upstream Workers AI model must support
function calling. ``@cf/meta/llama-3.3-70b-instruct-fp8-fast`` does.

Requires:
- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID

Optional:
- CLOUDFLARE_AI_GATEWAY_ID  (defaults to ``default``)

Install:
    uv pip install ddgs
"""

import asyncio

from agno.agent import Agent
from agno.models.cloudflare import Cloudflare
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Cloudflare(id="@cf/zai-org/glm-4.7-flash"),
    tools=[WebSearchTools()],
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
