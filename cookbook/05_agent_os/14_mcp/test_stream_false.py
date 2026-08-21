"""
Test MCP with stream=False agent (baseline)
===========================================

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/test_stream_false.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.mcp import build_mcp_server


async def test_mcp_with_stream_false_agent():
    """Test that run_agent works when agent has stream=False."""
    from fastmcp import Client

    agent = Agent(
        id="nonstream-test-agent",
        name="NonStream Test Agent",
        model=OpenAIResponses(id="gpt-5.5"),
        stream=False,  # Baseline - should definitely work
        instructions="You are a helpful assistant. Keep responses brief.",
    )

    agent_os = AgentOS(
        id="nonstream-test-os",
        agents=[agent],
        mcp_server=True,
    )

    mcp_server = build_mcp_server(agent_os)

    print("Testing MCP with stream=False agent...")
    print(f"Agent stream setting: {agent.stream}")

    async with Client(mcp_server) as client:
        print("\nCalling run_agent...")
        result = await client.call_tool(
            "run_agent",
            {
                "agent_id": "nonstream-test-agent",
                "message": "Say hello in one sentence.",
            },
        )

        print(f"\nResult content: {result.content}")
        print(f"Is error: {result.is_error}")

        if result.is_error:
            print("\nFAILED: MCP returned an error")
            return False

        print("\nSUCCESS: MCP works with stream=False agent!")
        return True


if __name__ == "__main__":
    success = asyncio.run(test_mcp_with_stream_false_agent())
    exit(0 if success else 1)
