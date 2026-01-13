"""
Here is a tool with reasoning capabilities to allow agents to manage user memories.

1. Run: `pip install openai agno lancedb tantivy sqlalchemy` to install the dependencies
2. Export your OPENAI_API_KEY
3. Run: `python cookbook/reasoning/tools/knowledge_tools.py` to run the agent
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.memory import MemoryTools

db = SqliteDb(db_file="tmp/memory.db")

john_doe_id = "john_doe@example.com"

memory_tools = MemoryTools(
    db=db,
)

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[memory_tools, DuckDuckGoTools()],
    instructions=[
        "You are a trip planner bot and you are helping the user plan their trip.",
        "You should use the DuckDuckGoTools to get information about the destination and activities.",
        "You should use the MemoryTools to store information about the user for future reference.",
        "Don't ask the user for more information, make up what you don't know.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response(
            "My name is John Doe and I like to hike in the mountains on weekends. "
            "I like to travel to new places and experience different cultures. "
            "I am planning to travel to Africa in December. ",
            stream=True,
            user_id=john_doe_id,
        )
    )

    asyncio.run(
        agent.aprint_response(
            "Make me a travel itinerary for my trip, and propose where I should go, how much I should budget, etc.",
            stream=True,
            user_id=john_doe_id,
        )
    )
