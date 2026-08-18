"""
Fast Reasoning
==============

Demonstrates this reasoning cookbook example.
"""

import time

from agno.agent import Agent
from agno.models.groq import Groq
from rich.console import Console


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
console = Console()

        console.print(response.content)
        console.print(f"\n[dim]Response time: {end - start:.2f}s[/dim]")

# Fast agent - no reasoning model
fast_agent = Agent(
    model=Groq(id="openai/gpt-oss-120b"),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
