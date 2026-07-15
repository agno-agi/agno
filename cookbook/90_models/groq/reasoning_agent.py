"""
Groq Reasoning Agent
====================

Cookbook example for `groq/reasoning_agent.py`.

Uses Groq's deepseek-r1-distill model which has native reasoning capabilities.
The model's reasoning content is extracted via <think> tags.
"""

from agno.agent import Agent
from agno.models.groq import Groq

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Create a reasoning agent using deepseek-r1-distill which has native reasoning
reasoning_agent = Agent(
    model=Groq(id="deepseek-r1-distill-llama-70b", temperature=0.6, top_p=0.95),
)

# Prompt the agent to solve the problem
reasoning_agent.print_response(
    "Is 9.11 bigger or 9.9?", stream=True, show_full_reasoning=True
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
