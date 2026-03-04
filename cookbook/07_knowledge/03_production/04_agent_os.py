"""
AgentOS: Serving Knowledge via API
====================================
AgentOS wraps your agents and knowledge instances in a FastAPI server,
exposing them as API endpoints. This is how you move from a script to
a running service.

Key concepts:
- Multiple Knowledge instances can share the same vector_db and contents_db
- Each instance is identified by its `name` property
- Content is isolated per instance via the `linked_to` field
- AgentOS exposes /knowledge endpoints for managing content

Setup:
1. Run Qdrant: ./cookbook/scripts/run_qdrant.sh
2. pip install uvicorn

See also: 03_multi_tenant.py for tenant isolation patterns.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Shared Infrastructure
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

vector_db = Qdrant(
    collection="agent_os_demo",
    url=qdrant_url,
    search_type=SearchType.hybrid,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

contents_db = SqliteDb(db_file="tmp/agent_os.db")

# ---------------------------------------------------------------------------
# Knowledge Instances
# ---------------------------------------------------------------------------

# Each instance has a unique name — content is isolated via linked_to
company_knowledge = Knowledge(
    name="Company Docs",
    description="Internal company documentation",
    vector_db=vector_db,
    contents_db=contents_db,
)

product_knowledge = Knowledge(
    name="Product FAQ",
    description="Product frequently asked questions",
    vector_db=vector_db,
    contents_db=contents_db,
)

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

support_agent = Agent(
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=company_knowledge,
    search_knowledge=True,
    markdown=True,
)

product_agent = Agent(
    name="Product Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=product_knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[support_agent, product_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Serves a FastAPI app. Use reload=True for local development.
    agent_os.serve(app="04_agent_os:app", reload=True)
