"""
Async Dependencies
=============================

Inject async resolvers. The framework awaits async callables automatically
so you can use `httpx.AsyncClient`, async DB drivers, or any awaitable.

Pitfall: only `arun` and `aprint_response` will await async dependencies
cleanly. Calling sync `run` with async dependencies logs a warning and
skips them.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


async def fetch_user_profile() -> dict:
    # Simulate an async DB or HTTP fetch
    await asyncio.sleep(0.1)
    return {
        "name": "Alice",
        "tier": "enterprise",
        "region": "us-west-2",
    }


async def fetch_quotas() -> dict:
    await asyncio.sleep(0.1)
    return {"monthly_tokens": 100_000, "used": 12_345}


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "user_profile": fetch_user_profile,
        "quotas": fetch_quotas,
    },
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response("Greet me by name and tell me my remaining token quota.")
    )
