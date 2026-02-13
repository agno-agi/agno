"""
Agents Sharing Memory
=====================

This example shows two agents sharing the same user memory.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a helpful assistant that can chat with users",
    db=db,
    update_memory_on_run=True,
)

research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a research assistant that can help users with their research questions",
    tools=[WebSearchTools()],
    db=db,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    john_doe_id = "john_doe@example.com"

    chat_agent.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends.",
        stream=True,
        user_id=john_doe_id,
    )

    chat_agent.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

    research_agent.print_response(
        "I love asking questions about quantum computing. What is the latest news on quantum computing?",
        stream=True,
        user_id=john_doe_id,
    )

    memories = research_agent.get_user_memories(user_id=john_doe_id)
    print("Memories about John Doe:")
    pprint(memories)
