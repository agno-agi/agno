import asyncio

from agno.agent import Agent
from agno.cli.console import console
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat

task = "How many 'r' are in the word 'strawberry'?"

regular_agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)
reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)


async def main():
    console.rule("[bold blue]Counting 'r's in 'strawberry'[/bold blue]")

    console.rule("[bold green]Regular Agent[/bold green]")
    await regular_agent.aprint_response(task, stream=True)
    console.rule("[bold yellow]Reasoning Agent[/bold yellow]")
    await reasoning_agent.aprint_response(task, stream=True)


asyncio.run(main())
