"""
Xiaomi MiMo Thinking Mode
=========================

Toggle thinking mode with the `use_thinking` flag. `use_thinking=True` makes the
model emit `reasoning_content` before its answer; `use_thinking=False` turns it
off for a faster, cheaper response. Leaving it unset (None) uses the model default.
"""

from agno.agent import Agent
from agno.models.xiaomi import MiMo

# ---------------------------------------------------------------------------
# Thinking enabled - returns reasoning_content
# ---------------------------------------------------------------------------

thinking_agent = Agent(
    model=MiMo(id="mimo-v2.5-pro", use_thinking=True),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Thinking disabled - faster, no reasoning_content
# ---------------------------------------------------------------------------

non_thinking_agent = Agent(
    model=MiMo(id="mimo-v2.5-pro", use_thinking=False),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    thinking_agent.print_response("Why is the sky blue?", stream=True)

    non_thinking_agent.print_response("Why is the sky blue?", stream=True)
