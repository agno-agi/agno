"""
Simple test script that connects to the MCP toolbox server
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp_toolbox import MCPToolbox

url = "http://127.0.0.1:5001"


async def run_agent(message: str) -> None:
    """Run an interactive CLI for the Hotel agent with the given message."""

    # Approach 1: Load specific toolset at initialization
    async with MCPToolbox(
        url=url, toolsets=["hotel-management", "booking-system"]
    ) as db_tools:
        # returns a list of tools from a toolset
        agent = Agent(
            model=OpenAIChat(),
            tools=[db_tools],
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
        )

        # Run an interactive command-line interface to interact with the agent.
        await agent.acli_app(input=message, stream=True)


async def run_agent_manual_loading(message: str) -> None:
    """Alternative approach: Manual loading with custom auth parameters."""

    # Approach 2: Manual loading with custom auth parameters
    async with MCPToolbox(url=url) as toolbox:  # No filter parameters
        # Load specific toolsets with custom auth
        hotel_tools = await toolbox.load_toolset(
            "hotel-management",
            auth_token_getters={"hotel_api": lambda: "your-hotel-api-key"},
            bound_params={"region": "us-east-1"},
        )

        booking_tools = await toolbox.load_toolset(
            "booking-system",
            auth_token_getters={"booking_api": lambda: "your-booking-api-key"},
            bound_params={"environment": "production"},
        )

        # Combine tools as needed
        selected_tools = []
        selected_tools.extend(hotel_tools)
        selected_tools.extend(booking_tools[:2])  # Only first 2 booking tools

        agent = Agent(
            tools=selected_tools,
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
            add_history_to_context=True,
            debug_mode=True,
        )

        await agent.acli_app(input=message, stream=True)


if __name__ == "__main__":
    # Use the original approach
    asyncio.run(run_agent(message=""))

    # Or use the manual loading approach
    # asyncio.run(run_agent_manual_loading(message=None))
