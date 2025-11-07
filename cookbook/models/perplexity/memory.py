"""
This recipe shows how to use personalized memories and summaries in an agent.
Steps:
1. Run: `./cookbook/scripts/run_pgvector.sh` to start a postgres container with pgvector
2. Run: `pip install openai sqlalchemy 'psycopg[binary]' pgvector` to install the dependencies
3. Run: `python cookbook/agents/personalized_memories_and_summaries.py` to run the agent
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.perplexity import Perplexity
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
agent = Agent(
    model=Perplexity(id="sonar-pro"),
    # Store the memories and summary in a database
    db=PostgresDb(db_url=db_url),
    enable_user_memories=True,
    enable_session_summaries=True,
)

# -*- Share personal information
agent.print_response("My name is john billings?", stream=True)
# -*- Print memories and summary
if agent.db:
    pprint(agent.get_user_memories(user_id="test_user"))
    pprint(
        agent.get_session(session_id="test_session").summary  # type: ignore
    )

# -*- Share personal information
agent.print_response("I live in nyc?", stream=True)
# -*- Print memories and summary
if agent.db:
    pprint(agent.get_user_memories(user_id="test_user"))
    pprint(
        agent.get_session(session_id="test_session").summary  # type: ignore
    )

# -*- Share personal information
agent.print_response("I'm going to a concert tomorrow?", stream=True)
# -*- Print memories and summary
if agent.db:
    pprint(agent.get_user_memories(user_id="test_user"))
    pprint(
        agent.get_session(session_id="test_session").summary  # type: ignore
    )

# Ask about the conversation
agent.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
