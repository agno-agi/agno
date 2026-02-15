"""
Memory Tools With Web Search
============================

This example shows how to use MemoryTools alongside WebSearchTools so an agent
can store and use user memory while planning a trip.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.memory import MemoryTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/memory.db")
john_doe_id = "john_doe@example.com"

memory_tools = MemoryTools(
    db=db,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[memory_tools, WebSearchTools()],
    instructions=[
        "You are a trip planner bot and you are helping the user plan their trip.",
        "You should use the WebSearchTools to get information about the destination and activities.",
        "You should use the MemoryTools to store information about the user for future reference.",
        "Don't ask the user for more information, make up what you don't know.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    await agent.aprint_response(
        "My name is John Doe and I like to hike in the mountains on weekends. "
        "I like to travel to new places and experience different cultures. "
        "I am planning to travel to Africa in December. ",
        stream=True,
        user_id=john_doe_id,
    )

    await agent.aprint_response(
        "Make me a travel itinerary for my trip, and propose where I should go, how much I should budget, etc.",
        stream=True,
        user_id=john_doe_id,
    )


if __name__ == "__main__":
    asyncio.run(main())
