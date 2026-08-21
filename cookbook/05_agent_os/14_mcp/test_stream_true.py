"""
Test issue #8062: MCP with stream=True agent
=============================================

This tests that AgentOS MCP works when an agent has stream=True.
Before the fix, this would crash with:
    TypeError: object async_generator_asend can't be used in 'await' expression

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/test_stream_true.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.mcp import build_mcp_server

# ---------------------------------------------------------------------------
# Test: MCP with stream=True agent
# ---------------------------------------------------------------------------


async def test_mcp_with_stream_true_agent():
    """Test that run_agent works when agent has stream=True."""
    from fastmcp import Client

    # Create agent with stream=True (the bug trigger)
    agent = Agent(
        id="stream-test-agent",
        name="Stream Test Agent",
        model=OpenAIResponses(id="gpt-5.5"),
        stream=True,  # THIS WAS THE BUG - caused crash before fix
        instructions="You are a helpful assistant. Keep responses brief.",
    )

    # Create AgentOS with MCP enabled
    agent_os = AgentOS(
        id="stream-test-os",
        agents=[agent],
        mcp_server=True,
    )

    # Use in-memory MCP client (no HTTP server needed)
    mcp_server = build_mcp_server(agent_os)

    print("Testing MCP with stream=True agent...")
    print(f"Agent stream setting: {agent.stream}")

    async with Client(mcp_server) as client:
        # List tools
        tools = await client.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Call run_agent - this would crash before the fix
        print("\nCalling run_agent...")
        result = await client.call_tool(
            "run_agent",
            {
                "agent_id": "stream-test-agent",
                "message": "Say hello in one sentence.",
            },
        )

        print(f"\nResult type: {type(result)}")
        print(f"Result content: {result.content}")
        print(f"Is error: {result.is_error}")

        if result.is_error:
            print("\nFAILED: MCP returned an error")
            return False

        # Check we got a response
        content_text = str(result.content)
        if not content_text or len(content_text) < 10:
            print("\nFAILED: No meaningful response")
            return False

        print("\nSUCCESS: MCP works with stream=True agent!")
        return True


# ---------------------------------------------------------------------------
# Run test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    success = asyncio.run(test_mcp_with_stream_true_agent())
    exit(0 if success else 1)
