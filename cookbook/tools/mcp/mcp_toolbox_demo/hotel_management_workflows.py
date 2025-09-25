#!/usr/bin/env python3
"""Sequential Workflow Demo: Hotel Search → Hotel Booking"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.mcp_toolbox import MCPToolbox
from agno.workflow.condition import Step
from agno.workflow.workflow import Workflow

# Configuration
url = "http://127.0.0.1:5001"

# Database for workflow
db = SqliteDb(db_file="tmp/workflow_demo.db")

# Create agents with different toolsets
search_agent = Agent(
    name="Hotel Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a hotel search expert. Find hotels based on user requirements.",
        "Always provide hotel IDs, names, locations, and availability.",
        "Be specific about which hotels are available for booking.",
    ],
)

booking_agent = Agent(
    name="Hotel Booking Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a booking specialist. Book hotels using the hotel IDs provided.",
        "Always confirm successful bookings with hotel name and ID.",
        "If booking fails, explain the reason clearly.",
    ],
)

# Define workflow steps
search_step = Step(
    name="Search Hotels",
    agent=search_agent,
)

booking_step = Step(
    name="Book Hotel",
    agent=booking_agent,
)

# Create the workflow
workflow = Workflow(
    name="hotel-workflow",
    description="Search and book hotels sequentially",
    db=db,
    steps=[search_step, booking_step],
)


async def run_workflow_demo():
    """Run the hotel workflow with MCP toolboxes"""

    # Create separate toolboxes for each agent's role
    search_tools = MCPToolbox(url=url, toolsets=["hotel-management"])
    booking_tools = MCPToolbox(url=url, toolsets=["booking-system"])

    async with search_tools, booking_tools:
        # Assign tools to agents
        search_agent.tools = [search_tools]
        booking_agent.tools = [booking_tools]

        # Input for the workflow
        user_request = "Find luxury hotels in Zurich and book the first available one"

        print("🏨 Hotel Search and Booking Workflow")
        print(f"Request: {user_request}")
        print("=" * 50)

        # Execute workflow
        result = await workflow.arun(user_request)

        print("\n✅ Workflow Result:")
        print(f"Content: {result.content}")
        print(f"Steps executed: {len(result.step_results)}")

        return result


if __name__ == "__main__":
    asyncio.run(run_workflow_demo())
