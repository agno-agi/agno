"""
Knowledge Management Tools
==========================

An operator agent that manages a knowledge base by chat: ingest a
website page by page, list what is loaded grouped by site, check a
site's status, and remove content.

This is the write side of knowledge. Hand it to a builder or operator
agent; end-user-facing agents get search only (search_knowledge=True).
remove_content requires confirmation by default.

Requirements:
- Qdrant running locally: ./cookbook/scripts/run_qdrant.sh
- OPENAI_API_KEY
- (optional) PARALLEL_API_KEY for higher-quality page extraction
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.knowledge import KnowledgeManagementTools
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Create Knowledge
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="Product Docs",
    contents_db=SqliteDb(db_file="tmp/knowledge_contents.db"),
    vector_db=Qdrant(
        collection="product-docs",
        url="http://localhost:6333",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create the operator agent
# ---------------------------------------------------------------------------
operator = Agent(
    name="Knowledge Operator",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    # ingest_path reads any path the server process can read, so it is off by default.
    # Turn it on only where the operator is trusted with the machine's filesystem.
    tools=[
        KnowledgeManagementTools(knowledge=knowledge, max_pages=25, ingest_path=True)
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
async def main() -> None:
    await operator.aprint_response(
        "Load https://docs.agno.com into the knowledge base."
    )
    # Folders work the same way: one row per file, refreshed by content digest
    # await operator.aprint_response("Load the folder ./product-docs into the knowledge base.")
    await operator.aprint_response("What do we have loaded now?")


if __name__ == "__main__":
    asyncio.run(main())
