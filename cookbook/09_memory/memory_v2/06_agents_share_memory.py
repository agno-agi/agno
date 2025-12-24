"""Shared Memory - Multiple agents share the same user memory.

Demonstrates:
- Two agents (chat + research) sharing the same database
- User info learned by one agent is available to the other
- Memory isolation by user_id
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from rich import print_json

DB_FILE = "tmp/shared_memory.db"
USER_ID = "john_doe"

db = SqliteDb(db_file=DB_FILE)

# Agent 1: Chat agent that learns about the user
chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a helpful assistant that chats with users",
    db=db,
    update_memory_on_run=True,
    markdown=True,
)

# Agent 2: Research agent that uses user context for personalized research
research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a research assistant that helps users find information",
    tools=[DuckDuckGoTools(cache_results=True)],
    db=db,
    update_memory_on_run=True,
    markdown=True,
)

if __name__ == "__main__":
    # Chat agent learns about the user
    chat_agent.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends.",
        user_id=USER_ID,
        stream=True,
    )

    chat_agent.print_response(
        "What are my hobbies?",
        user_id=USER_ID,
        stream=True,
    )

    # Research agent now has access to the same user memory
    research_agent.print_response(
        "I love asking questions about quantum computing. What is the latest news on quantum computing?",
        user_id=USER_ID,
        stream=True,
    )

    # Both agents share the same memory
    print("\n" + "=" * 60)
    print("SHARED USER MEMORY")
    print("=" * 60)

    user = chat_agent.get_user_memory_v2(USER_ID)
    if user:
        print_json(json.dumps(user.to_dict()))

    # Verify research agent sees the same memory
    user_from_research = research_agent.get_user_memory_v2(USER_ID)
    if user_from_research:
        print(
            "\nResearch agent sees same memory:", user_from_research.user_id == USER_ID
        )
