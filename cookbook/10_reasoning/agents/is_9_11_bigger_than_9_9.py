"""
Decimal Comparison Reasoning
============================

Demonstrates regular, built-in, and DeepSeek-backed reasoning for 9.11 vs 9.9.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat
from rich.console import Console

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
console = Console()

task = "9.11 and 9.9 -- which is bigger?"

regular_agent_openai = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

cot_agent_openai = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

regular_agent_claude = Agent(model=Claude("claude-3-5-sonnet-20241022"), markdown=True)

deepseek_agent_claude = Agent(
    model=Claude("claude-3-5-sonnet-20241022"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

deepseek_agent_openai = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.rule("[bold blue]Regular OpenAI Agent[/bold blue]")
    regular_agent_openai.print_response(task, stream=True)

    console.rule("[bold yellow]OpenAI Built-in Reasoning Agent[/bold yellow]")
    cot_agent_openai.print_response(task, stream=True, show_full_reasoning=True)

    console.rule("[bold green]Regular Claude Agent[/bold green]")
    regular_agent_claude.print_response(task, stream=True)

    console.rule("[bold cyan]Claude + DeepSeek Reasoning Agent[/bold cyan]")
    deepseek_agent_claude.print_response(task, stream=True)

    console.rule("[bold magenta]OpenAI + DeepSeek Reasoning Agent[/bold magenta]")
    deepseek_agent_openai.print_response(task, stream=True)
