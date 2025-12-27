"""Fast Reasoning with Groq.

This example demonstrates Groq's ultra-fast reasoning capabilities with
DeepSeek-R1 and other reasoning models.

Requirements:
    pip install agno groq

Environment:
    export GROQ_API_KEY="gsk_..."

Usage:
    python cookbook/reasoning/models/groq/fast_reasoning.py

What to expect:
    - Sub-second response times with reasoning
    - Speed comparison across models
    - Low-latency reasoning for production use cases
"""

import time

from agno.agent import Agent
from agno.models.groq import Groq
from rich.console import Console

console = Console()


# Test task requiring reasoning
task = "What is 23 × 47? Show your step-by-step reasoning."

console.rule("[bold cyan]Groq Fast Reasoning Demo[/bold cyan]")

# Test with Llama 3.3 (reasoning capable)
console.print("\n[bold blue]Llama 3.3 70B Versatile (Reasoning Capable)[/bold blue]")
try:
    start = time.time()
    agent_deepseek = Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        markdown=True,
    )
    response = agent_deepseek.run(task, stream=False)
    end = time.time()

    console.print(response.content)
    console.print(f"\n[dim]Response time: {end - start:.2f}s[/dim]")

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
        model=Groq(id="llama-3.3-70b-versatile"),
        markdown=True,
    )
    response = agent_llama.run(task, stream=False)
    end = time.time()

    console.print(response.content)
    console.print(f"\n[dim]Response time: {end - start:.2f}s[/dim]")
except Exception as e:
    console.print(f"[red]Error: {e}[/red]")
