"""Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality with MCP Servers in your Agno tools.
It shows how to:
- Handle user confirmation during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `uv pip install openai httpx rich agno` to install dependencies.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from rich.console import Console
from rich.prompt import Prompt

console = Console()

mcp_tools = MCPTools(
    transport="streamable-http",
    url="https://docs.agno.com/mcp",
    requires_confirmation_tools=["SearchAgno"],  # Note: Tool names are case-sensitive
)

agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[mcp_tools],
    markdown=True,
    db=SqliteDb(db_file="tmp/confirmation_required_toolkit.db"),
)


async def main():
    async for run_event in agent.arun("What is Agno?", stream=True):
        if run_event.is_paused:
            for requirement in run_event.active_requirements:
                if requirement.needs_confirmation:
                    # Ask for confirmation
                    console.print(
                        f"Tool name [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
                    )
                    message = (
                        Prompt.ask(
                            "Do you want to continue?", choices=["y", "n"], default="y"
                        )
                        .strip()
                        .lower()
                    )

                    if message == "n":
                        requirement.reject()
                    else:
                        requirement.confirm()

            async for resp in agent.acontinue_run(  # type: ignore
                run_id=run_event.run_id,
                requirements=run_event.requirements,
                stream=True,
            ):
                print(resp.content, end="")
            else:
                print(run_event.content, end="")

    # Or for simple debug flow
    # await agent.aprint_response("what is Agno?", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
