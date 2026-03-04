"""
Multi-Tenant Knowledge: Isolating Data Per Tenant
===================================================
When multiple Knowledge instances share the same vector database,
use isolate_vector_search to ensure each instance only searches its own data.

This is essential for multi-tenant applications where different users
or departments should only access their own documents.

Behavior:
- isolate_vector_search=False (default): Searches ALL vectors in the database.
- isolate_vector_search=True: Only searches vectors tagged with this instance's name.

Important: Existing data without linked_to metadata won't be found when
isolation is enabled. You'll need to re-index to add the metadata.

See also: ../02_building_blocks/04_filtering.py for metadata-based filtering.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

# Both knowledge instances share the same vector collection
vector_db = Qdrant(
    collection="multi_tenant",
    url=qdrant_url,
    search_type=SearchType.hybrid,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Tenant A: only sees its own data
tenant_a_knowledge = Knowledge(
    name="Tenant A",
    vector_db=vector_db,
    isolate_vector_search=True,
)

# Tenant B: only sees its own data
tenant_b_knowledge = Knowledge(
    name="Tenant B",
    vector_db=vector_db,
    isolate_vector_search=True,
)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

agent_a = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=tenant_a_knowledge,
    search_knowledge=True,
    markdown=True,
)

agent_b = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=tenant_b_knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Insert different content for each tenant
        await tenant_a_knowledge.ainsert(
            name="Tenant A Docs",
            text_content="Tenant A uses PostgreSQL for their primary database.",
        )
        await tenant_b_knowledge.ainsert(
            name="Tenant B Docs",
            text_content="Tenant B runs their workloads on AWS with DynamoDB.",
        )

        print("\n" + "=" * 60)
        print("TENANT A: Only sees its own data")
        print("=" * 60 + "\n")

        agent_a.print_response("What database do we use?", stream=True)

        print("\n" + "=" * 60)
        print("TENANT B: Only sees its own data")
        print("=" * 60 + "\n")

        agent_b.print_response("What cloud provider do we use?", stream=True)

    asyncio.run(main())
