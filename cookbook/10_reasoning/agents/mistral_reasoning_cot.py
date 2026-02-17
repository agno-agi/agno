"""
Mistral Reasoning COT
=====================

Demonstrates built-in chain-of-thought reasoning with Mistral.
"""

from agno.agent import Agent
from agno.models.mistral import MistralChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
reasoning_agent = Agent(
    model=MistralChat(id="mistral-large-latest"),
    reasoning=True,
    markdown=True,
    use_json_mode=True,
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
