from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url)
# *******************************


def get_memory_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = False,
) -> Agent:
    return Agent(
        name="Memory Agent",
        id="memory-agent",
        session_id=session_id,
        user_id=user_id,
        model=OpenAIChat(id="gpt-4.1"),
        add_history_to_context=True,
        num_history_runs=5,
        add_datetime_to_context=True,
        markdown=True,
        debug_mode=debug_mode,
        # Set a database
        db=db,
        # Enable memory
        enable_user_memories=True,
        # Add a tool to search the web
        tools=[DuckDuckGoTools()],
    )
