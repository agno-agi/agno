"""
This recipe shows how to use personalized memories and summaries in an agent.
Steps:
1. Run: `./cookbook/scripts/run_pgvector.sh` to start a postgres container with pgvector
2. Run: `pip install ollama sqlalchemy 'psycopg[binary]' pgvector` to install the dependencies
3. Run: `python cookbook/models/lmstudio/memory.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.lmstudio import LMStudio
from agno.storage.agent.postgres import PostgresAgentStorage

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
agent = Agent(
    model=LMStudio(id="qwen2.5-7b-instruct-1m"),
    # Store the memories and summary in a database
    memory=Memory(
        db=PostgresMemoryDb(table_name="agent_memory", db_url=db_url),
    ),
    enable_user_memories=True,
    enable_session_summaries=True,
    # Store agent sessions in a database
    storage=PostgresAgentStorage(
        table_name="personalized_agent_sessions", db_url=db_url
    ),
    # Show debug logs so, you can see the memory being created
    # debug_mode=True,
)

# -*- Share personal information
agent.print_response("My name is john billings?", stream=True)

# -*- Share personal information
agent.print_response("I live in nyc?", stream=True)

# -*- Share personal information
agent.print_response("I'm going to a concert tomorrow?", stream=True)

# Ask about the conversation
agent.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
