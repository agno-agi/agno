"""Local Reasoning with Ollama.

This example demonstrates privacy-first reasoning using locally-run models
with Ollama. No data leaves your machine.

Requirements:
    pip install agno ollama
    # Install Ollama: https://ollama.ai
    ollama pull qwq:32b
    ollama pull deepseek-r1:8b

Usage:
    python cookbook/reasoning/models/ollama/local_reasoning.py

What to expect:
    - Complete data privacy (runs locally)
    - No API costs or usage limits
    - Comparison of local reasoning models
    - Trade-offs between privacy and speed
"""

from agno.agent import Agent
from agno.models.ollama import Ollama
from rich.console import Console

console = Console()


# Test task
task = "What is 23 × 47? Show your step-by-step reasoning."

console.rule("[bold cyan]Local Reasoning with Ollama[/bold cyan]")

# Test with QwQ (Alibaba's reasoning model)
console.print("\n[bold blue]QwQ:32B (Alibaba Reasoning Model)[/bold blue]")
console.print("[dim]Running locally with complete privacy...[/dim]\n")

try:
    agent_qwq = Agent(
        model=Ollama(id="qwq:32b"),
        markdown=True,
    )
    agent_qwq.print_response(task, stream=True, show_full_reasoning=True)
except Exception as e:
    console.print(f"[red]Error: {e}[/red]")
    console.print(
        "[yellow]Make sure Ollama is running and qwq:32b is installed:[/yellow]"
    )
    console.print("  ollama pull qwq:32b")

# Test with DeepSeek-R1:8B (smaller, faster)
console.print("\n[bold green]DeepSeek-R1:8B (Smaller, Faster)[/bold green]")
console.print("[dim]Running locally with complete privacy...[/dim]\n")

try:
    agent_deepseek = Agent(
        model=Ollama(id="deepseek-r1:8b"),
        markdown=True,
    )
    agent_deepseek.print_response(task, stream=True, show_full_reasoning=True)
except Exception as e:
    console.print(f"[red]Error: {e}[/red]")
    console.print(
        "[yellow]Make sure Ollama is running and deepseek-r1:8b is installed:[/yellow]"
    )
    console.print("  ollama pull deepseek-r1:8b")
