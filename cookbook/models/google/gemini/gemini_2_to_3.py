"""
Async example using Gemini with tool calls.
"""

import asyncio
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

session_id = str(uuid4())

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    db=SqliteDb(db_file="tmp/data.db"),
    tools=[DuckDuckGoTools()],
    markdown=True,
    add_history_to_context=True,
)

asyncio.run(
    agent.aprint_response(
        "Whats the current news in France?", session_id=session_id, stream=True
    )
)

# Create a new agent with Gemini 3 Pro and re-use the history from the previous session
agent = Agent(
    model=Gemini(id="gemini-3-pro-preview"),
    db=SqliteDb(db_file="tmp/data.db"),
    markdown=True,
    add_history_to_context=True,
)
asyncio.run(
    agent.aprint_response(
        "Write a 2 sentence story the biggest news highlight in our conversation.",
        session_id=session_id,
        stream=True,
    )
)
