"""
Multimodal Embedders: Cross-Modal Semantic Search
===================================================
Multimodal embedders place text, images, and audio into the same vector space.
This enables cross-modal search -- e.g. a text query can find relevant images.

This example uses Gemini Embedding 2 (gemini-embedding-2-preview), which
natively supports text, image, audio, and video embedding.

We load a coffee production chart (image) into the knowledge base, then ask
a text question about it. The agent retrieves and reads the image directly.

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
        await knowledge.ainsert(
            images=[
                Image(
                    filepath=resources / "coffee_production.png", mime_type="image/png"
                )
            ],
            skip_if_exists=True,
        )

        agent.print_response(
            "Which countries produce the most coffee?",
            stream=True,
        )

    asyncio.run(main())
