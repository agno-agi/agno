"""
Memory Tools
============

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.memory import MemoryTools
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    db = SqliteDb(db_file="tmp/memory.db")

    john_doe_id = "john_doe@example.com"

    memory_tools = MemoryTools(
        db=db,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[memory_tools, WebSearchTools()],
        instructions=[
            "You are a personalized trip planner that remembers everything about the user.",
            "Always start by retrieving stored memories to personalize your response.",
            "Store user preferences, interests, and trip details using MemoryTools.",
            "Use WebSearchTools to find real destinations, costs, and activities.",
            "Be proactive: propose specific plans tailored to the user's known interests instead of asking questions.",
        ],
        markdown=True,
    )

    agent.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends. "
        "I like to travel to new places and experience different cultures. "
        "I am planning to travel to Africa in December. ",
        stream=True,
        user_id=john_doe_id,
    )

    agent.print_response(
        "Make me a travel itinerary for my trip, and propose where I should go, how much I should budget, etc.",
        stream=True,
        user_id=john_doe_id,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
