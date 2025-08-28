"""
This recipe shows how to use personalized memories and summaries in an agent.
Steps:
1. Run: `./cookbook/scripts/run_pgvector.sh` to start a postgres container with pgvector
2. Run: `pip install openai sqlalchemy 'psycopg[binary]' pgvector` to install the dependencies
3. Run: `python cookbook/agents/personalized_memories_and_summaries.py` to run the agent
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.meta import Llama
from rich.pretty import pprint

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    user_id="test_user",
    session_id="test_session",
    # Pass the database to the Agent
    db=db,
    # Enable user memories
    enable_user_memories=True,
    # Enable session summaries
    enable_session_summaries=True,
    # Show debug logs so, you can see the memory being created
)

# -*- Share personal information
agent.print_response("My name is John Billings", stream=True)

# -*- Print memories and session summary
if agent.db:
    pprint(agent.get_user_memories(user_id="test_user"))
    pprint(
        agent.get_session(session_id="test_session").summary  # type: ignore
    )

# -*- Share personal information
agent.print_response("I live in NYC", stream=True)
# -*- Print memories and session summary
if agent.db:
    pprint(agent.get_user_memories(user_id="test_user"))
    pprint(
        agent.get_session(session_id="test_session").summary  # type: ignore
    )


# Ask about the conversation
agent.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
