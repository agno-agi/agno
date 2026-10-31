"""
GPT-5.6 Sol With Tools
======================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-sol"),
        tools=[WebSearchTools(enable_news=False)],
        instructions="Use tables to display data.",
        markdown=True,
    )

    agent.print_response("Write a report comparing NVDA to TSLA", stream=True)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
