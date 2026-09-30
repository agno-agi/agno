"""Use Oracle Database as the database for an agent, asynchronously.

Requires Oracle Database 19c or later. Start one locally with:
    ./cookbook/scripts/run_oracle.sh

Run `uv pip install "agno[oracle]" openai ddgs` to install dependencies.
"""

import asyncio

from agno.agent import Agent
from agno.db.oracle import AsyncOracleDb
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# AsyncOracleDb requires the oracle+oracledb_async:// prefix: python-oracledb's
# asyncio support works only in thin mode, and this prefix is what selects it.
db_url = "oracle+oracledb_async://ai:ai@localhost:1521/?service_name=FREEPDB1"
db = AsyncOracleDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[WebSearchTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main():
    await agent.aprint_response("How many people live in Canada?")
    await agent.aprint_response("What is their national anthem called?")


if __name__ == "__main__":
    asyncio.run(main())
