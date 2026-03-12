"""
Multimodal Embedders: Text, Images, and Audio in a Shared Vector Space
=======================================================================

Multimodal embedders convert different content types (text, images, audio)
into the same vector space, enabling cross-modal semantic search -- e.g.
searching images with text queries or finding similar content across formats.

This example uses Gemini Embedding 2, Google's first natively multimodal
embedding model. It demonstrates:
1. Embedding text, images, and audio into a shared space
2. Storing multimodal embeddings in a knowledge base
3. Querying across modalities with an agent

Requirements:
  - GOOGLE_API_KEY environment variable
  - PostgreSQL with pgvector (./cookbook/scripts/run_pgvector.sh)
  - google-genai >= 1.52.0
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image
from agno.models.google import Gemini
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

RESOURCES = Path(__file__).parent.parent / "testing_resources"

embedder = GeminiEmbedder(id="gemini-embedding-2-preview", dimensions=768)

knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="multimodal_embedder_demo",
        embedder=embedder,
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- 1. Text embedding ---
        print("\n" + "=" * 60)
        print("TEXT EMBEDDING")
        print("=" * 60 + "\n")

        text_emb = embedder.get_embedding(
            "The quick brown fox jumps over the lazy dog."
        )
        print("Dimensions: %d" % len(text_emb))
        print("First 5 values: %s" % text_emb[:5])

        # --- 2. Image embedding ---
        print("\n" + "=" * 60)
        print("IMAGE EMBEDDING")
        print("=" * 60 + "\n")

        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        img_emb = embedder.get_image_embedding(image)
        print("Dimensions: %d" % len(img_emb))
        print("First 5 values: %s" % img_emb[:5])

        # --- 3. Audio embedding ---
        print("\n" + "=" * 60)
        print("AUDIO EMBEDDING")
        print("=" * 60 + "\n")

        audio = Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")
        audio_emb = embedder.get_audio_embedding(audio)
        print("Dimensions: %d" % len(audio_emb))
        print("First 5 values: %s" % audio_emb[:5])

        # --- 4. Mixed multimodal embedding (text + image in one call) ---
        print("\n" + "=" * 60)
        print("MULTIMODAL EMBEDDING (text + image)")
        print("=" * 60 + "\n")

        mixed_emb = embedder.get_multimodal_embedding(["A red square image", image])
        print("Dimensions: %d" % len(mixed_emb))
        print("First 5 values: %s" % mixed_emb[:5])

        # --- 5. Agent with multimodal knowledge base ---
        print("\n" + "=" * 60)
        print("AGENT WITH KNOWLEDGE BASE")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf", skip_if_exists=True
        )

        agent = Agent(
            model=Gemini(id="gemini-2.5-flash"),
            knowledge=knowledge,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response(
            "What work experience does the candidate have?", stream=True
        )

    asyncio.run(main())
