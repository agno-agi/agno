"""Basic Anthropic Claude Reasoning Example.

This cookbook demonstrates how to use Anthropic Claude with extended thinking support.

Requirements:
    pip install agno anthropic

Environment:
    export ANTHROPIC_API_KEY="sk-ant-..."


What to expect:
    - Claude will use extended thinking to solve the problem
    - You'll see the reasoning process in reasoning_content
    - The response will be well-reasoned and accurate
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from rich.console import Console

console = Console()

# Classic reasoning test: comparing decimal numbers
task = "9.11 and 9.9 -- which is bigger? Explain your reasoning step by step."

# Create a regular agent (no reasoning)
regular_agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    markdown=True,
)

# Create an agent with extended thinking
reasoning_agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    reasoning_model=Claude(
        id="claude-sonnet-4-5",
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
)

console.rule("[bold blue]Regular Claude Agent (No Reasoning)[/bold blue]")
console.print("This agent will answer directly without extended thinking.\n")
regular_agent.print_response(task, stream=True)

console.rule("[bold green]Claude with Extended Thinking[/bold green]")
console.print("This agent uses extended thinking to analyze the problem deeply.\n")
reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)

console.rule("[bold cyan]Accessing Reasoning Content[/bold cyan]")
response = reasoning_agent.run(task, stream=False)
if response.reasoning_content:
    console.print(
        f"[dim]Reasoning tokens used: {len(response.reasoning_content.split())}[/dim]"
    )
    console.print(
        f"\n[bold]First 300 chars of reasoning:[/bold]\n{response.reasoning_content[:300]}..."
    )
