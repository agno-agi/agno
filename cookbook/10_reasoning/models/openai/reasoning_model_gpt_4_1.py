"""
Reasoning Model Gpt 4 1
=======================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.openai.responses import OpenAIResponses


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        reasoning_model=OpenAIResponses(id="gpt-4.1"),
    )
    agent.print_response(
        "Solve the trolley problem. Evaluate multiple ethical frameworks. "
        "Include an ASCII diagram of your solution.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
