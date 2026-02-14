"""
WatsonX Default COT Fallback
============================

Demonstrates default chain-of-thought behavior with an IBM WatsonX model.
"""

from agno.agent import Agent
from agno.models.ibm import WatsonX

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
reasoning_agent = Agent(
    model=WatsonX(id="meta-llama/llama-3-3-70b-instruct"),
    reasoning=True,
    debug_mode=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    reasoning_agent.print_response(
        "Give me steps to write a python script for fibonacci series",
        stream=True,
        show_full_reasoning=True,
    )
