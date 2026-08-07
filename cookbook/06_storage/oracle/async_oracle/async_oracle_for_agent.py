"""Use Async Oracle as the database for an agent.
Run `uv pip install openai duckduckgo-search sqlalchemy oracledb agno` to install dependencies.
"""

import asyncio
import uuid

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.oracle import AsyncOracleDb
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "oracle+oracledb_async://ai:ai@localhost:1521/?service_name=FREEPDB1"
db = AsyncOracleDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main():
    """Run the agent queries in the same event loop"""
    session_id = str(uuid.uuid4())
    await agent.aprint_response(
        "How many people live in Canada?", session_id=session_id
    )
    await agent.aprint_response(
        "What is their national anthem called?", session_id=session_id
    )
    session_data = await db.get_session(
        session_id=session_id, session_type=SessionType.AGENT
    )
    print("\n=== SESSION DATA ===")
    print(session_data.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
