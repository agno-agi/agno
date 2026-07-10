"""
9 11 Or 9 9
===========

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.groq import Groq


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=Groq(
            id="qwen/qwen3-32b",
            temperature=0.6,
            max_tokens=1024,
            top_p=0.95,
        ),
        reasoning=True,
        markdown=True,
    )
    agent.print_response(
        "9.11 and 9.9 -- which is bigger?", stream=True, show_full_reasoning=True
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
