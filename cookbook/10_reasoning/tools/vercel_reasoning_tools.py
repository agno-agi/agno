"""
Vercel Reasoning Tools
======================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.vercel import V0
from agno.tools.reasoning import ReasoningTools
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    reasoning_agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[
            ReasoningTools(add_instructions=True, add_few_shot=True),
            WebSearchTools(),
        ],
        instructions=[
            "Use tables to display data",
            "Only output the report, no other text",
        ],
        markdown=True,
    )
    reasoning_agent.print_response(
        "Write a report on TSLA",
        stream=True,
        show_full_reasoning=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
