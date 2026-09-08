"""A public agent that pauses for confirmation and resumes through native MCP.

Run `public_approval.py serve`, then `public_approval.py demo` in another terminal.
Use `public_approval.py --check` to validate configuration without provider calls.
"""

import argparse
import asyncio
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig
from agno.os.public import PublicSurface
from agno.tools import tool
from fastmcp import Client


# Reuse the agent; each conversation gets its own session.
@tool(requires_confirmation=True)
def prepare_note(title: str) -> str:
    """Prepare a note after the caller confirms its title."""
    return f"Prepared note: {title}"


db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/public_approval"
    )
)
agent = Agent(
    id="approval-agent",
    name="Approval Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[prepare_note],
    instructions="Use prepare_note when asked to prepare a note. Report the outcome concisely.",
)
agent_os = AgentOS(
    id="public-approval",
    agents=[agent],
    db=db,
    public=PublicSurface(agents=[agent], mcp=True),
    mcp=MCPConfig(
        tools=[agent],
        default_tools=False,
        stateless=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
    ),
)
app = agent_os.get_app()


async def demonstrate() -> None:
    url = getenv("PAGE_DEMO_SERVER_URL", "http://localhost:7777").rstrip("/")
    async with Client(url + "/mcp") as client:
        result = await client.call_tool(
            "approval-agent",
            {"message": "Prepare a note titled My first public approval."},
        )
        paused = result.structured_content
        if not paused or paused.get("status") != "PAUSED":
            print(result)
            return
        requirements = paused["requirements"]
        for requirement in requirements:
            execution = requirement["tool_execution"]
            print(
                "Requested action:", execution["tool_name"], execution.get("tool_args")
            )
        confirmed = input("Approve this action? [y/N] ").strip().lower() == "y"
        for requirement in requirements:
            requirement["tool_execution"]["confirmed"] = confirmed
        # Keep these opaque handles private: anonymous callers use them as capabilities.
        resumed = await client.call_tool(
            "continue_run",
            {
                "agent_id": paused["agent_id"],
                "session_id": paused["session_id"],
                "run_id": paused["run_id"],
                "requirements": requirements,
            },
        )
        print(
            resumed.structured_content.get("content")
            if resumed.structured_content
            else resumed
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["serve", "demo"], default="serve")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print("Public approval configuration validated.")
    elif args.mode == "demo":
        asyncio.run(demonstrate())
    else:
        agent_os.serve(
            app="public_approval:app", host="127.0.0.1", port=7777, reload=False
        )
