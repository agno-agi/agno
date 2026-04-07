"""
Plan Itinerary
==============

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    # ---------------------------------------------------------------------------
    # Create Agent
    # ---------------------------------------------------------------------------
    task = "Plan an itinerary from Los Angeles to Las Vegas"

    reasoning_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=DeepSeek(id="deepseek-reasoner"),
        markdown=True,
    )

    # ---------------------------------------------------------------------------
    # Run Agent
    # ---------------------------------------------------------------------------
    if __name__ == "__main__":
        reasoning_agent.print_response(task, stream=True)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
