"""
Personalized memory and session summaries with vLLM.

Prerequisites:
1. Start a Postgres + pgvector container (helper script is provided):

       ./cookbook/scripts/run_pgvector.sh

2. Install dependencies:

       pip install sqlalchemy 'psycopg[binary]' pgvector

3. Run a vLLM server (any open model).  Example with Phi-3 (no gating):

       vllm serve microsoft/Phi-3-mini-128k-instruct \
         --dtype float32 \
         --enable-auto-tool-choice \
         --tool-call-parser pythonic

Then execute this script – it will remember facts you tell it and generate a
summary.
"""

from agno.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.vllm import Vllm
from agno.storage.postgres import PostgresStorage
from rich.pretty import pprint

# Change this if your Postgres container is running elsewhere
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=Vllm(id="microsoft/Phi-3-mini-128k-instruct"),
    # Persist memories & summaries in the database
    memory=Memory(
        db=PostgresMemoryDb(table_name="agent_memory", db_url=DB_URL),
    ),
    enable_user_memories=True,
    enable_session_summaries=True,
    # Store agent sessions too
    storage=PostgresStorage(table_name="personalized_agent_sessions", db_url=DB_URL),
)

# Share personal details; the agent should remember them.
agent.print_response("My name is John Billings.", stream=True)
print("Current memories →")
pprint(agent.memory.memories)
print("Current summary →")
pprint(agent.memory.summaries)

agent.print_response("I live in NYC.", stream=True)
print("Memories →")
pprint(agent.memory.memories)
print("Summary →")
pprint(agent.memory.summaries)

agent.print_response("I'm going to a concert tomorrow.", stream=True)
print("Memories →")
pprint(agent.memory.memories)
print("Summary →")
pprint(agent.memory.summaries)

# Ask the agent to recall
agent.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
