"""
Together Reasoning Agent
========================

Cookbook example for `together/reasoning_agent.py`.
"""

from agno.agent import Agent
from agno.models.together import Together

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Together(
        id="Qwen/Qwen3-235B-A22B-Thinking-2507",
    ),
    reasoning=True,
)
agent.print_response("How many r are in the word 'strawberry'?", show_reasoning=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
