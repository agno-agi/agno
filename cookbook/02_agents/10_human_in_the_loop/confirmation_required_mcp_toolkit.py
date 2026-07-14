"""
Confirmation Required MCP Toolkit
=============================

Human-in-the-Loop: Adding User Confirmation to Tool Calls with MCP Servers.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from rich.console import Console
from rich.prompt import Prompt

console = Console()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
mcp_tools = MCPTools(
    transport="streamable-http",
    url="https://docs.agno.com/mcp",
    requires_confirmation_tools=["SearchAgno"],  # Note: Tool names are case-sensitive
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[mcp_tools],
    markdown=True,
    db=SqliteDb(db_file="tmp/confirmation_required_toolkit.db"),
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main():
    async for run_event in agent.arun("What is Agno?", stream=True):
        if run_event.is_paused:
            # Handle confirmation requirements
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

            # Continue the run after handling all confirmations
            async for resp in agent.acontinue_run(
                run_id=run_event.run_id,
                requirements=run_event.requirements,
                stream=True,
            ):
                if resp.content:
                    print(resp.content, end="")
        else:
            # Not paused - print the streaming content
            if run_event.content:
                print(run_event.content, end="")

    print()  # Final newline


if __name__ == "__main__":
    asyncio.run(main())
