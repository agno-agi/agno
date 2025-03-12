"""
Be sure to set your DEEPSEEK_API_KEY environment variable before running this script.
"""

from agno.agent import Agent
from agno.cli.console import console
from agno.models.anthropic import Claude
from agno.models.deepinfra import DeepInfra
from agno.models.openai import OpenAIChat

task = "9.11 and 9.9 -- which is bigger?"

regular_agent_claude = Agent(model=Claude("claude-3-5-sonnet-20241022"))
reasoning_agent_claude = Agent(
    model=Claude("claude-3-5-sonnet-20241022"),
    reasoning_model=DeepInfra(
        id="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        temperature=0.6,
        max_tokens=1024,
        top_p=0.95,
    ),
)

regular_agent_openai = Agent(model=OpenAIChat(id="gpt-4o"))
reasoning_agent_openai = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    reasoning_model=DeepInfra(
        id="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        temperature=0.6,
        max_tokens=1024,
        top_p=0.95,
    ),
)

console.rule("[bold blue]Regular Claude Agent[/bold blue]")
regular_agent_claude.print_response(task, stream=True)

console.rule("[bold green]Claude Reasoning Agent[/bold green]")
reasoning_agent_claude.print_response(task, stream=True)

console.rule("[bold red]Regular OpenAI Agent[/bold red]")
regular_agent_openai.print_response(task, stream=True)

console.rule("[bold yellow]OpenAI Reasoning Agent[/bold yellow]")
reasoning_agent_openai.print_response(task, stream=True)
