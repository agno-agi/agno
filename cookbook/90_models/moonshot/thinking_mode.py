"""
Moonshot Thinking Mode
======================

Kimi models reason by default, so you get reasoning_content out of the box. Use the
`use_thinking` flag to control it: `use_thinking=True` forces it on, `use_thinking=False`
turns it off for a faster, cheaper response.

Note that thinking cannot be turned off on every model - Kimi K3 always reasons.
"""

from agno.agent import Agent
from agno.models.moonshot import MoonShot

# ---------------------------------------------------------------------------
# Thinking enabled (default) - returns reasoning_content
# ---------------------------------------------------------------------------

thinking_agent = Agent(model=MoonShot(id="kimi-k2.6"), markdown=True)

# ---------------------------------------------------------------------------
# Thinking disabled - faster, no reasoning_content
# ---------------------------------------------------------------------------

non_thinking_agent = Agent(
    model=MoonShot(id="kimi-k2.6", use_thinking=False),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    thinking_agent.print_response("Why is the sky blue?", stream=True)

    non_thinking_agent.print_response("Why is the sky blue?", stream=True)
