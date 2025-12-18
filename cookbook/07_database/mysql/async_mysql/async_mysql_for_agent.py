"""Use Async MySQL as the database for an agent.
Run `pip install openai duckduckgo-search sqlalchemy asyncmy agno` to install dependencies.
"""

import asyncio
import uuid

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.mysql import AsyncMySQLDb
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "mysql+asyncmy://ai:ai@localhost:3306/ai"
db = AsyncMySQLDb(db_url=db_url)

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)


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
