"""
GPT-5.6 Sol
===========

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-sol"),
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
