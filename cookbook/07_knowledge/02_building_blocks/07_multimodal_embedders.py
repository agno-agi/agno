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
        # Insert an image with a description into the knowledge base
        await knowledge.ainsert(
            images=[Image(filepath=resources / "sample.png", mime_type="image/png")],
            text_content="A red square test image",
            skip_if_exists=True,
        )

        # Insert a PDF document
        await knowledge.ainsert(
            path=str(resources / "cv_1.pdf"),
            skip_if_exists=True,
        )

        print("\n" + "=" * 60)
        print("Gemini Embedding 2 (multimodal embedder)")
        print("=" * 60 + "\n")

        # Text queries search across both text and image embeddings
        agent.print_response(
            "What work experience does the candidate have and what images are in the knowledge base?",
            stream=True,
        )

    asyncio.run(main())
