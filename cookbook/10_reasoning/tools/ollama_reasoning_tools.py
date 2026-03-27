"""
Ollama Reasoning Tools
======================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.ollama.chat import Ollama
from agno.tools.reasoning import ReasoningTools
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    reasoning_agent = Agent(
        model=Ollama(id="llama3.2:latest"),
        tools=[
            ReasoningTools(
                enable_think=True,
                enable_analyze=True,
                add_instructions=True,
                add_few_shot=True,
            ),
            WebSearchTools(),
        ],
        instructions="Use tables where possible",
        markdown=True,
    )
    reasoning_agent.print_response(
        "Write a report comparing NVDA to TSLA",
        stream=True,
        show_full_reasoning=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
