"""
Level 5: Agentic System (Production API)
==========================================
The most complete level. Production infrastructure for agentic software.
Upgrade from development databases to PostgreSQL + PgVector, add tracing,
and expose everything as an API with AgentOS.

This builds on Level 4 by adding:
- PostgresDb: Production-grade session storage
- PgVector: Production-grade vector search
- AgentOS: FastAPI server with web UI, tracing, and session management

Prerequisites:
    Start PostgreSQL with PgVector:
        ./cookbook/scripts/run_pgvector.sh

    This starts a Postgres container on port 5532 with:
        user=ai, password=ai, database=ai

Run standalone:
    python cookbook/levels_of_agentic_software/level_5_api.py

Run via Agent OS:
    python cookbook/levels_of_agentic_software/run.py
    Then visit https://os.agno.com and select "L5 Coding Agent"

Example prompt:
    "Write a function that validates email addresses using regex"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("tmp/code")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Production Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Knowledge: Static docs (PgVector for production)
# ---------------------------------------------------------------------------
docs_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="coding_standards",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Knowledge: Dynamic learnings (PgVector for production)
# ---------------------------------------------------------------------------
learned_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="coding_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a production coding agent that learns and improves over time.

## Workflow

1. Search your knowledge and learnings for relevant context
2. Check if the user has preferences you should follow
3. Write code that follows conventions and user preferences
4. Save the code to a file and run it to verify
5. Save any valuable insights or patterns for future use

## Rules

- Always search knowledge and learnings before writing code
- Apply user preferences from memory when writing code
- Save useful coding patterns and insights as learnings
- Follow project conventions from the knowledge base
- No emojis\
"""

# ---------------------------------------------------------------------------
# Create Production Agent
# ---------------------------------------------------------------------------
l5_coding_agent = Agent(
    name="L5 Coding Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=instructions,
    tools=[
        CodingTools(base_dir=WORKSPACE, all=True),
        ReasoningTools(),
    ],
    knowledge=docs_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=learned_knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    enable_agentic_memory=True,
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo (standalone)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    l5_coding_agent.print_response(
        "Write a function that validates email addresses using regex. "
        "Save it to email_validator.py and test it with valid and invalid examples.",
        user_id="dev@example.com",
        session_id="production_test",
        stream=True,
    )
