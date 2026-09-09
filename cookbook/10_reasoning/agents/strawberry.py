"""
Strawberry Letter Counting
==========================

Demonstrates regular vs reasoning-backed agents for counting tasks.
"""

import asyncio

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses
from rich.console import Console

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
console = Console()

task = "How many 'r' are in the word 'strawberry'?"

regular_agent = Agent(model=OpenAIResponses(id="gpt-5.6"), markdown=True)

reasoning_agent = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)


async def run_agents() -> None:
    console.rule("[bold blue]Counting 'r' In 'strawberry'[/bold blue]")

    console.rule("[bold green]Regular Agent[/bold green]")
    await regular_agent.aprint_response(task, stream=True)

    console.rule("[bold cyan]Reasoning Agent (DeepSeek)[/bold cyan]")
    await reasoning_agent.aprint_response(task, stream=True, show_full_reasoning=True)


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(run_agents())
