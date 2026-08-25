"""
Router Fallback
===============

Cookbook example for `ramp/fallback.py`.

Router serves the first candidate that answers, so a rate limit or an outage at one provider
falls through to the next instead of failing the run. Candidates are the `catalog_id` values
from `GET https://api.router.com/v1/models`, optionally suffixed with a service tier.

`models` replaces `id` rather than adding to it: Router rejects a request that carries both.
"""

from agno.agent import Agent
from agno.models.ramp import RampRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=RampRouter(
        models=[
            "openai:gpt-5.6-luna",
            "anthropic:claude-haiku-4-5",
            "openai:gpt-5-nano:flex",
        ],
        # Move on to the next candidate if a provider has not answered in time
        provider_timeout=30,
        # Attribute the spend in the Router dashboard
        metadata={"team": "platform"},
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Write a haiku about routing", stream=True)
