"""Run `pip install duckduckgo-search sqlalchemy openai` to install dependencies."""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage
from agno.utils.log import log_warning
from agno.utils.session_search import vector_match_message
from scipy.spatial.distance import cosine

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

storage = PostgresStorage(
    table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
)
# storage.create_vectors(session_id="test_session")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    user_id="test_user",
    session_id="test_session",
    storage=PostgresStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    search_history=True,
)

agent.print_response(
    message="How many people live in Canada?",
)
