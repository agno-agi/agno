"""
Reasoning Summary
=================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    # Setup the reasoning Agent
    agent = Agent(
        model=OpenAIResponses(
            id="o4-mini",
            reasoning_summary="auto",  # Requesting a reasoning summary
        ),
        tools=[WebSearchTools(enable_news=False)],
        instructions="Use tables to display the analysis",
        markdown=True,
    )

    agent.print_response(
        "Write a brief report comparing NVDA to TSLA",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
