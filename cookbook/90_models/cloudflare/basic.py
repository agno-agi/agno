"""
Cloudflare AI Gateway (basic)
=============================

Cookbook example for Cloudflare AI Gateway OpenAI-compatible unified API.

Requires:
- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID

Optional:
- CLOUDFLARE_AI_GATEWAY_ID (defaults to the ``default`` gateway)

Default model is **Workers AI** (only Cloudflare token + account id). You can paste a catalog binding:
``Agent(model="cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast")``, the full gateway id, or ``Cloudflare()`` defaults.

Set ``CLOUDFLARE_API_TOKEN`` and ``CLOUDFLARE_ACCOUNT_ID`` in your shell before running (see README),
not in this file.

For switching models (OpenRouter-style ``id`` string), see ``switch_model.py`` in this folder.

For ``google/...`` or ``openai/...`` you need a supported gateway provider name, BYOK keys in the
dashboard, and a model id from the Cloudflare docs — otherwise you may see **Invalid provider** (HTTP 400)
or upstream **401** errors.
"""

import asyncio

from agno.agent import Agent
from agno.models.cloudflare import Cloudflare

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Cloudflare(),
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
