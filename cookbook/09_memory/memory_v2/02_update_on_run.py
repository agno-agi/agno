"""Automatic Learning - Memory deepens through conversation.

This continues Sarah's story from 01_basic.py.
The agent AUTOMATICALLY extracts new information without explicit tools.

Run after 01_basic.py to see memory accumulate.
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    update_memory_on_run=True,
    markdown=True,
)

if __name__ == "__main__":
    existing = agent.get_user_memory_v2(USER_ID)
    if existing:
        print("Existing profile:")
        print_json(json.dumps(existing.to_dict()))

    agent.print_response(
        "We're migrating our legacy Flask services to FastAPI for better async support. "
        "The payment API I mentioned is the first one we're converting.",
        user_id=USER_ID,
        stream=True,
    )

    agent.print_response(
        "By the way, I prefer seeing error handling patterns rather than just try/except blocks. "
        "Show me structured error responses with proper HTTP status codes.",
        user_id=USER_ID,
        stream=True,
    )

    agent.print_response(
        "How should I implement rate limiting for our payment API?",
        user_id=USER_ID,
        stream=True,
    )

    agent.print_response(
        "That was exactly what I needed - concise with real code. "
        "The FastAPI middleware approach is perfect for our use case.",
        user_id=USER_ID,
        stream=True,
    )

    agent.print_response(
        "I'm the tech lead for a team of 4 backend engineers. "
        "We're also looking into implementing OAuth2 for our microservices.",
        user_id=USER_ID,
        stream=True,
    )

    print("\n" + "=" * 60)
    print("UPDATED MEMORY")
    print("=" * 60)

    user = agent.get_user_memory_v2(USER_ID)
    if user:
        print_json(json.dumps(user.to_dict()))
