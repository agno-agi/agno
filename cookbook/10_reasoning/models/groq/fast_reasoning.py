"""
Fast Reasoning
==============

Compares Groq speed with and without a reasoning model.
"""

import time

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.groq import Groq
from rich.console import Console

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
console = Console()

task = "What is 23 x 47? Show your step-by-step reasoning."

# Fast agent - no reasoning model
fast_agent = Agent(
    model=Groq(id="openai/gpt-oss-120b"),
    markdown=True,
)

# Reasoning agent - uses DeepSeek for thinking
reasoning_agent = Agent(
    model=Groq(id="qwen/qwen3.6-27b"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.rule("[bold cyan]Groq Fast Reasoning Demo[/bold cyan]")

    console.rule("[bold green]Fast Agent (No Reasoning)[/bold green]")
    start = time.time()
    fast_agent.print_response(task, stream=True)
    console.print(f"\n[dim]Response time: {time.time() - start:.2f}s[/dim]")

    console.rule("[bold blue]Reasoning Agent (DeepSeek)[/bold blue]")
    start = time.time()
    reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)
    console.print(f"\n[dim]Response time: {time.time() - start:.2f}s[/dim]")
