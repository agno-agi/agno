"""
Deepseek Thinking Mode
======================

DeepSeek V4 models run with thinking mode enabled by default, so you get
reasoning_content out of the box. Use the `use_thinking` flag to control it:
`use_thinking=True` forces it on, `use_thinking=False` turns it off for a faster,
cheaper response.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek

# ---------------------------------------------------------------------------
# Thinking enabled (default) - returns reasoning_content
# ---------------------------------------------------------------------------

thinking_agent = Agent(model=DeepSeek(id="deepseek-v4-flash"), markdown=True)

# ---------------------------------------------------------------------------
# Thinking disabled - faster, no reasoning_content
# ---------------------------------------------------------------------------

non_thinking_agent = Agent(
    model=DeepSeek(id="deepseek-v4-flash", use_thinking=False),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    thinking_agent.print_response("Why is the sky blue?", stream=True)

    non_thinking_agent.print_response("Why is the sky blue?", stream=True)
