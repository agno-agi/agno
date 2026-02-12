"""
Async example using Gemini with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3-pro-preview"),
    db=SqliteDb(db_file="tmp/data.db"),
    tools=[WebSearchTools()],
    markdown=True,
    add_history_to_context=True,
)

asyncio.run(agent.aprint_response("Whats the current news in France?", stream=True))

# Non-streaming response
asyncio.run(
    agent.aprint_response(
        "Write a 2 sentence story the biggest news highlight in our conversation."
    )
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
