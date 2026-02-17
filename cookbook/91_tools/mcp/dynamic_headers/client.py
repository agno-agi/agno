"""Agent with MCP tools using Dynamic Headers"""

import asyncio
from typing import TYPE_CHECKING, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.mcp import MCPTools

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.team import Team
# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def main():
    """Example showing dynamic headers with different users."""

    # Step 1: Define your header provider
    # This function can receive RunContext, Agent and/or Team based on its signature
    def header_provider(
        run_context: RunContext,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> dict:
        """
        Generate dynamic headers from RunContext and Agent.

        The header_provider can accept any combination of these parameters:
        - run_context: The RunContext for the current agent or team run
        - agent: The contextual Agent instance
        - team: The contextual Team instance

        The RunContext contains:
        - run_id: Unique ID for this agent run
        - user_id: User ID passed to agent.arun()
        - session_id: Session ID passed to agent.arun()
        - metadata: Dict of custom metadata passed to agent.arun()
        """
        headers = {
            "X-User-ID": run_context.user_id or "unknown",
            "X-Session-ID": run_context.session_id or "unknown",
            "X-Run-ID": run_context.run_id,
            "X-Tenant-ID": run_context.metadata.get("tenant_id", "no-tenant")
            if run_context.metadata
            else "no-tenant",
            # You can also access agent and team properties if needed
            "X-Agent-Name": agent.name
            if agent
            else team.name
            if team
            else "unnamed-agno-entity",
        }
        return headers

    # Step 2: Create MCPTools with header_provider
    # This enables dynamic headers for all MCP tool calls
    mcp_tools = MCPTools(
        url="http://localhost:8000/mcp",  # Your MCP server URL
        transport="streamable-http",  # Use streamable-http or sse for headers
        header_provider=header_provider,  # This enables dynamic headers!
    )

    # Step 3: Connect to MCP server
    await mcp_tools.connect()
    print("Connected to MCP server")
    print(f"   Available tools: {list(mcp_tools.functions.keys())}\n")

    try:
        # Step 4: Create agent with MCP tools
        agent_1 = Agent(
            name="agent-1",
            model=OpenAIChat(id="gpt-5.2"),
            tools=[mcp_tools],
            markdown=False,
        )

        # Step 5: Run agent with different users
        # The agent automatically creates RunContext and injects it into tools!

        # Example 1: User "neel"
        print("=" * 60)
        print("Example 1: Running as user 'neel'")
        print("=" * 60)

        response1 = await agent_1.arun(
            "Please use the greet tool to greet me. My name is neel.",
            user_id="neel",  # ← Goes into RunContext.user_id
            session_id="session-1",  # ← Goes into RunContext.session_id
            metadata={  # ← Goes into RunContext.metadata
                "tenant_id": "tenant-1",
            },
        )
        print(f"Response: {response1.content}\n")

        # Example 2: User "dirk"
        print("=" * 60)
        print("Example 2: Running as user 'dirk'")
        print("=" * 60)

        agent_2 = Agent(
            name="agent-2",
            model=OpenAIChat(id="gpt-5.2"),
            tools=[mcp_tools],
            markdown=False,
        )
        response2 = await agent_2.arun(
            "Please use the greet tool to greet me. My name is dirk.",
            user_id="dirk",  # Different user!
            session_id="session-2",  # Different session!
            metadata={
                "tenant_id": "tenant-2",  # Different tenant!
            },
        )
        print(f"Response: {response2.content}\n")

        print("=" * 60)
        print("Success! Check your MCP server logs to see the headers.")
        print("=" * 60)

    finally:
        # Step 6: Clean up
        await mcp_tools.close()
        print("\nConnection closed")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
