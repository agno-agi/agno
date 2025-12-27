"""
Personalized memory and session summaries with vLLM.
Prerequisites:
1. Start a Postgres + pgvector container (helper script is provided):
       ./cookbook/scripts/run_pgvector.sh
2. Install dependencies:
       pip install sqlalchemy 'psycopg[binary]' pgvector
3. Run a vLLM server (any open model).  Example with Phi-3:
       vllm serve microsoft/Phi-3-mini-128k-instruct \
         --dtype float32 \
         --enable-auto-tool-choice \
         --tool-call-parser pythonic
Then execute this script – it will remember facts you tell it and generate a
summary.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.vllm import VLLM
from agno.utils.pprint import pprint

# Change this if your Postgres container is running elsewhere
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=VLLM(id="microsoft/Phi-3-mini-128k-instruct"),
    db=PostgresDb(db_url=DB_URL),
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
