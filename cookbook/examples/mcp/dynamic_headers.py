"""
Dynamic Headers with MCP Tools

This example demonstrates how to use dynamic headers with MCP tools in Agno.
Dynamic headers allow you to send different authentication tokens, user IDs,
and other context-specific information with each agent run.

Use Cases:
- Multi-tenant applications
- Per-user authentication
- Request tracking with unique IDs
- Tenant-specific data isolation

Key Features:
- One session per agent run (efficient)
- Automatic RunContext injection
- Different headers per user/tenant
- Type-safe header provider

---

FastMCP Server Example (save as server.py):

```python
from fastmcp import FastMCP
from fastmcp.server import Context

mcp = FastMCP("My Server")

@mcp.tool
async def greet(name: str, ctx: Context) -> str:
    '''
    Greet a user with personalized information from headers.
    IMPORTANT: ctx parameter MUST be last!
    '''
    # Get the HTTP request object
    request = ctx.get_http_request()

    # Access headers (lowercase!)
    user_id = request.headers.get('x-user-id', 'unknown')
    tenant_id = request.headers.get('x-tenant-id', 'unknown')

    print(f" User: {user_id}, Tenant: {tenant_id}")

    return f"Hello, {name}! (User: {user_id}, Tenant: {tenant_id})"

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000)
```

To run this example:
1. Start the FastMCP server: python server.py
2. Run this client: python dynamic_headers_client.py
"""
import asyncio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from agno.run import RunContext


async def main():
    """Example showing dynamic headers with different users."""

    # Step 1: Define your header provider
    # This function receives the RunContext and returns headers as a dict
    def header_provider(ctx: RunContext) -> dict:
        """
        Generate dynamic headers from RunContext.

        The RunContext contains:
        - run_id: Unique ID for this agent run
        - user_id: User ID passed to agent.arun()
        - session_id: Session ID passed to agent.arun()
        - metadata: Dict of custom metadata passed to agent.arun()
        """
        headers = {
            "X-User-ID": ctx.user_id or "unknown",
            "X-Session-ID": ctx.session_id or "unknown",
            "X-Run-ID": ctx.run_id,
            "X-Tenant-ID": ctx.metadata.get("tenant_id", "no-tenant") if ctx.metadata else "no-tenant",
        }
        return headers

    # Step 2: Create MCPTools with header_provider
    # This enables dynamic headers for all MCP tool calls
    mcp_tools = MCPTools(
        url="http://localhost:8000/mcp",  # Your MCP server URL
        transport="streamable-http",       # Use streamable-http or sse for headers
        header_provider=header_provider,   # ← This enables dynamic headers!
    )

    # Step 3: Connect to MCP server
    await mcp_tools.connect()
    print(f"✅ Connected to MCP server")
    print(f"   Available tools: {list(mcp_tools.functions.keys())}\n")

    try:
        # Step 4: Create agent with MCP tools
        agent = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[mcp_tools],
            markdown=False,
        )

        # Step 5: Run agent with different users
        # The agent automatically creates RunContext and injects it into tools!

        # Example 1: User "neel"
        print("=" * 60)
        print("Example 1: Running as user 'neel'")
        print("=" * 60)

        response1 = await agent.arun(
            "Please use the greet tool to greet me. My name is neel.",
            user_id="neel",                    # ← Goes into RunContext.user_id
            session_id="session-1",            # ← Goes into RunContext.session_id
            metadata={                         # ← Goes into RunContext.metadata
                "tenant_id": "tenant-1",
            },
        )
        print(f"Response: {response1.content}\n")

        # Example 2: User "dirk"
        print("=" * 60)
        print("Example 2: Running as user 'dirk'")
        print("=" * 60)

        response2 = await agent.arun(
            "Please use the greet tool to greet me. My name is dirk.",
            user_id="dirk",                    # Different user!
            session_id="session-2",            # Different session!
            metadata={
                "tenant_id": "tenant-2",       # Different tenant!
            },
        )
        print(f"Response: {response2.content}\n")

        print("=" * 60)
        print("Both requests completed with different headers!")
        print("=" * 60)
        print("\nCheck your MCP server logs to see the different headers received.")

    finally:
        # Step 6: Clean up
        await mcp_tools.close()
        print("\nConnection closed")


if __name__ == "__main__":
    asyncio.run(main())
