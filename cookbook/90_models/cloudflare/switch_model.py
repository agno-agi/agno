"""
Cloudflare AI Gateway — switching models (OpenRouter-style ids)
==============================================================

Same idea as OpenRouter: you pick one slash-separated route per client via ``id``.
Changing model = new ``Cloudflare(id=...)`` or a new ``Agent(model="cloudflare:...")`` string.

OpenRouter also supports ``models=[...]`` for fallbacks in the request body. The Cloudflare
compat API does not; use AI Gateway Dynamic Routes and ``id="dynamic/<route>"`` instead.

Requires ``CLOUDFLARE_API_TOKEN`` and ``CLOUDFLARE_ACCOUNT_ID`` (see README).

How to pick another **Workers AI** model (see https://developers.cloudflare.com/workers-ai/models/):

1. Open the catalog and choose a **Text generation** model.
2. On that model's doc page, copy the binding id from the box (e.g. ``@cf/google/gemma-4-26b-a4b-it``).
3. Paste it straight into Agno: ``Cloudflare(id="@cf/google/gemma-4-26b-a4b-it")`` or
   ``Agent(model="cloudflare:@cf/google/gemma-4-26b-a4b-it")``. Agno prepends ``workers-ai/`` for the gateway.
   You can still pass the full form ``workers-ai/@cf/...`` if you prefer.

**Gemini** (Google's API product) is not the same as **Gemma** / Llama on Workers AI. Do not invent
``@cf/.../gemini-...`` slugs — they are not in the catalog. For Gemini via the gateway use a
``google/...`` route and BYOK (see README), not ``workers-ai/...``.
"""

from agno.agent import Agent
from agno.models.cloudflare import DEFAULT_GATEWAY_MODEL, Cloudflare

# Second Workers AI model: paste the same string as the catalog "copy" box on the model page.
ALT_WORKERS_MODEL = "@cf/google/gemma-4-26b-a4b-it"

if __name__ == "__main__":
    # Default Workers AI model (no explicit id).
    Agent(model=Cloudflare(), markdown=True).print_response("Say hello in five words.")

    # Same as OpenRouter: pass the gateway route string as ``id``.
    Agent(model=Cloudflare(id=DEFAULT_GATEWAY_MODEL), markdown=True).print_response(
        "Say hello in five words."
    )

    # Switch model: new client instance with a different ``id``.
    Agent(model=Cloudflare(id=ALT_WORKERS_MODEL), markdown=True).print_response(
        "Say hello in five words."
    )

    # String syntax: everything after the first colon is the gateway ``model`` id.
    Agent(
        model=f"cloudflare:{ALT_WORKERS_MODEL}",
        markdown=True,
    ).print_response("Say hello in five words.")

    # Dynamic route configured in the Cloudflare dashboard (example id only).
    # Agent(model=Cloudflare(id="dynamic/my-route"), markdown=True).print_response("...")
