"""
Basic Reasoning
===============

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from rich.console import Console


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    console = Console()

    # Classic reasoning test
    task = "9.11 and 9.9 -- which is bigger? Explain your reasoning."

    # Create a regular agent (no reasoning)
    regular_agent = Agent(
        model=Gemini(id="gemini-2.5-flash"),
        markdown=True,
    )

    # Create an agent with thinking budget
    reasoning_agent = Agent(
        model=Gemini(id="gemini-2.5-flash"),
        reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        markdown=True,
    )

    console.rule("[bold blue]Regular Gemini Agent (No Reasoning)[/bold blue]")
    console.print("This agent will answer directly without extended thinking.\n")
    regular_agent.print_response(task, stream=True)

    console.rule("[bold green]Gemini with Thinking Budget[/bold green]")
    console.print("This agent uses thinking budget to analyze the problem.\n")
    reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)

    console.rule("[bold cyan]Accessing Reasoning Content[/bold cyan]")
    response = reasoning_agent.run(task, stream=False)
    if response.reasoning_content:
        console.print(
            f"[dim]Reasoning tokens used: ~{len(response.reasoning_content.split())}[/dim]"
        )
        console.print(
            f"\n[bold]Reasoning process:[/bold]\n{response.reasoning_content[:400]}..."
        )
    else:
        console.print("[yellow]No reasoning content available[/yellow]")


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
