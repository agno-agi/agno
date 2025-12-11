import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

from db.session import docs_db
from db.url import get_db_url

# ============================================================================
# Knowledge Base
# ============================================================================
knowledge = Knowledge(
    name="Agno Documentation",
    vector_db=PgVector(
        table_name="agno_docs",
        db_url=get_db_url(),
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=docs_db,
)

# ============================================================================
# Create Knowledge Agent
# ============================================================================
knowledge_agent = Agent(
    id="docs-assistant",
    name="Agno Docs Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge,
    search_knowledge=True,
    enable_agentic_knowledge_filters=True,
    description="You are a helpful assistant that answers questions about Agno.",
    instructions=dedent("""\
        Always search the knowledge base before answering.
        If you can't find relevant information, say so clearly.
        Include code examples when available.
    """),
    markdown=True,
    debug_mode=True,
)

if __name__ == "__main__":
    # Add content to knowledge base
    print("Adding content to knowledge base...")
    asyncio.run(
        knowledge.add_content_async(
            url="https://docs.agno.com/llms-full.txt",
        )
    )
    print("Content added to knowledge base.")