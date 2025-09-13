import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.playground import Playground
from agno.tools.mcp_toolbox import MCPToolbox

agent = Agent(
    tools=[],
    instructions=dedent(
        """ \
        You're a helpful hotel assistant. You handle hotel searching, booking and
        cancellations. When the user searches for a hotel, mention it's name, id,
        location and price tier. Always mention hotel ids while performing any
        searches. This is very important for any operations. For any bookings or
        cancellations, please provide the appropriate confirmation. Be sure to
        update checkin or checkout dates if mentioned by the user.
        Don't ask for confirmations from the user.
    """
    ),
    markdown=True,
    show_tool_calls=True,
    add_history_to_messages=True,
    debug_mode=False,
)


async def main():
    """Main function to serve the playground"""
    try:
        async with MCPToolbox(url="http://127.0.0.1:5001") as tools:
            agent.tools.extend([tools])
            playground = Playground(
                agents=[agent],
                name="Test MCP Playground",
                description="A playground for testing MCP tools",
            )
            app = playground.get_app()
            await playground.serve(app="test_async_tools:app", reload=True)
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())
