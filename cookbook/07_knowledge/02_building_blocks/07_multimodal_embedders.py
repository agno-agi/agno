"""
Multimodal Embedders: Cross-Modal Semantic Search
===================================================
Multimodal embedders place text, images, and audio into the same vector space.
This enables cross-modal search -- e.g. a text query can find relevant images.

This example uses Gemini Embedding 2 (gemini-embedding-2-preview), which
natively supports text, image, audio, and video embedding.

We load a coffee guide (text) and a coffee production chart (image) into the
same knowledge base, then ask questions that require both sources.

See also: 06_embedders.py for comparing text-only embedders.

Prerequisites:
    - pip install agno[google,pgvector]
    - PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
    - GOOGLE_API_KEY set
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.media import Image
from agno.models.google import Gemini
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
resources = Path(__file__).parent.parent / "testing_resources"

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
        # 1. Insert text knowledge -- a coffee brewing guide
        await knowledge.ainsert(
            path=str(resources / "coffee.md"),
            skip_if_exists=True,
        )

        # 2. Insert an image -- a coffee production chart
        #    text_content is a short label shown to the agent when this result is retrieved
        await knowledge.ainsert(
            images=[
                Image(
                    filepath=resources / "coffee_production.png", mime_type="image/png"
                )
            ],
            text_content="Coffee production by country (2024)",
            skip_if_exists=True,
        )

        print("\n" + "=" * 60)
        print("Multimodal Knowledge: Coffee Guide + Production Data")
        print("=" * 60 + "\n")

        # Query that benefits from both text (brewing methods) and image (production data)
        agent.print_response(
            "Which countries produce the most coffee and what brewing methods "
            "would best highlight the flavor profiles from those regions?",
            stream=True,
        )

    asyncio.run(main())
