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
def run_example() -> None:
    console = Console()

    # Test task requiring reasoning
    task = "What is 23 × 47? Show your step-by-step reasoning."

    console.rule("[bold cyan]Groq Fast Reasoning Demo[/bold cyan]")

    # Test with Llama 3.3 (reasoning capable)
    console.print(
        "\n[bold blue]Llama 3.3 70B Versatile (Reasoning Capable)[/bold blue]"
    )
    try:
        start = time.time()
        agent_deepseek = Agent(
            model=Groq(id="openai/gpt-oss-120b"),
            markdown=True,
        )
        response = agent_deepseek.run(task, stream=False)
        end = time.time()

task = "What is 23 x 47? Show your step-by-step reasoning."

        if response.reasoning_content:
            reasoning_len = len(response.reasoning_content.split())
            console.print(f"[dim]Reasoning depth: ~{reasoning_len} words[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")

    # Test with Llama for comparison
    console.print("\n[bold green]Llama 3.3 70B (Standard Mode)[/bold green]")
    try:
        start = time.time()
        agent_llama = Agent(
            model=Groq(id="openai/gpt-oss-120b"),
            markdown=True,
        )
        response = agent_llama.run(task, stream=False)
        end = time.time()

        console.print(response.content)
        console.print(f"\n[dim]Response time: {end - start:.2f}s[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")

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
