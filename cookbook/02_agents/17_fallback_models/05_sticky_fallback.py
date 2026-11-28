"""
Fallback Models — Sticky Fallback
====================================

By default every call tries the primary model first, so while the primary is
down each run pays for a failed attempt (and its retries) before the fallback
takes over.

Set ``sticky=True`` to keep using the fallback model that took over. Later
calls go straight to it until it fails, or until ``retry_primary_after``
seconds have passed, and then the primary is tried again.

Context-window fallbacks never stick: they depend on the request, not on the
primary model's health.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.fallback import FallbackConfig
from agno.models.openai import OpenAIResponses


def on_fallback(
    primary_model_id: str, fallback_model_id: str, error: Exception
) -> None:
    print(f"[fallback] {primary_model_id} -> {fallback_model_id}")


# ---------------------------------------------------------------------------
# Create Agent with a sticky fallback
# The primary model points to an unreachable server so it fails once, then
# the fallback serves every later run without the primary being retried.
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.6-luna", base_url="http://localhost:1/v1", retries=0
    ),
    fallback_config=FallbackConfig(
        on_error=[Claude(id="claude-sonnet-5-5")],
        sticky=True,
        # Try the primary again after 5 minutes. Leave unset to stay on the
        # fallback until it fails.
        retry_primary_after=300,
        callback=on_fallback,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The primary fails, the fallback takes over and the callback fires
    agent.print_response("Name one planet.", stream=True)

    sticky_model = agent.fallback_config.get_sticky_fallback(agent.model)
    print(f"Sticky fallback: {sticky_model.id if sticky_model else None}")

    # Goes straight to the fallback: no failed primary call, no callback
    agent.print_response("Name another planet.", stream=True)

    # Force the next run to try the primary first again
    agent.fallback_config.clear_sticky_fallback()
