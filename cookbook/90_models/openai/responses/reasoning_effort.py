"""
Openai Reasoning Effort
=======================

Cookbook example for `openai/responses/reasoning_effort.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# reasoning_effort sets how much the model thinks before it answers. OpenAI names
# "none", "minimal", "low", "medium", "high", "xhigh" and "max", and each model page
# lists the ones that model takes. reasoning_summary asks for a summary of the thinking.
agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5", reasoning_effort="xhigh", reasoning_summary="auto"
    ),
    markdown=True,
)

agent.print_response(
    "Three switches downstairs, one bulb upstairs. One trip up. Which switch?",
    stream=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
