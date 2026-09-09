"""
Serve Knowledge with AgentOS
============================

Serve one local knowledge base through an AgentOS and share the same instance
with an agent so uploaded content is immediately available for search.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/10_knowledge/basic.py
Try: Run rest_api_knowledge.py from this folder in another terminal
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.vectordb.chroma import ChromaDb

# ---------------------------------------------------------------------------
# Create Knowledge-Aware AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="knowledge-db",
    db_file="tmp/knowledge.db",
)

knowledge = Knowledge(
    name="AgentOS Knowledge",
    description="Local content managed through the AgentOS knowledge API.",
    contents_db=db,
    vector_db=ChromaDb(
        collection="agentos_knowledge",
        path="tmp/knowledge_chroma",
        persistent_client=True,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge_assistant = Agent(
    id="knowledge-assistant",
    name="Knowledge Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    knowledge=knowledge,
    search_knowledge=True,
    instructions=(
        "Answer concisely. Search the knowledge base before answering questions "
        "about stored content."
    ),
)

agent_os = AgentOS(
    id="knowledge-os",
    description="AgentOS serving one local knowledge base.",
    db=db,
    agents=[knowledge_assistant],
    knowledge=[knowledge],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Knowledge Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    knowledge.insert(
        name="AgentOS knowledge overview",
        text_content=(
            "AgentOS exposes content upload, processing status, listing, "
            "semantic search, and deletion through the knowledge REST API."
        ),
        metadata={"source": "10_knowledge/basic.py"},
        skip_if_exists=True,
    )
    agent_os.serve(app=app)
