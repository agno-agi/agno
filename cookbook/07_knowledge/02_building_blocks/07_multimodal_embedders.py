"""
Multimodal Embedders: Cross-Modal Semantic Search
===================================================
Multimodal embedders place text, images, and audio into the same vector space.
This enables cross-modal search -- e.g. a text query can find relevant images.

This example uses Gemini Embedding 2 (gemini-embedding-2-preview), which
natively supports text, image, audio, and video embedding.

See also: 06_embedders.py for comparing text-only embedders.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.google import Gemini
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="multimodal_embedder_demo",
        embedder=GeminiEmbedder(id="gemini-embedding-2-preview", dimensions=768),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            skip_if_exists=True,
        )

        print("\n" + "=" * 60)
        print("Gemini Embedding 2 (multimodal embedder)")
        print("=" * 60 + "\n")

        agent.print_response(
            "What work experience does the candidate have?",
            stream=True,
        )

    asyncio.run(main())
