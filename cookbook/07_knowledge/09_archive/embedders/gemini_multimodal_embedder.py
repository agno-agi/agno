"""
Gemini Multimodal Embedder
==========================

Demonstrates multimodal embedding with Gemini Embedding 2 — Google's first
natively multimodal embedding model that embeds text, images, audio, and
mixed content into a shared vector space.

Requirements:
  - GOOGLE_API_KEY env var
  - google-genai>=1.52.0
"""

import asyncio
from pathlib import Path

from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
RESOURCES = Path(__file__).parent.parent.parent / "testing_resources"

embedder = GeminiEmbedder(id="gemini-embedding-2-preview", dimensions=768)

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="gemini_multimodal_embeddings",
        embedder=embedder,
    ),
    max_results=2,
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
async def main() -> None:
    # Text embedding
    text_emb = embedder.get_embedding("The quick brown fox jumps over the lazy dog.")
    print(f"Text embedding: {len(text_emb)} dims, first 5: {text_emb[:5]}")

    # Image embedding (local file)
    image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
    img_emb = embedder.get_embedding(image)
    print(f"Image embedding: {len(img_emb)} dims, first 5: {img_emb[:5]}")

    # Audio embedding (local file)
    audio = Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")
    audio_emb = embedder.get_embedding(audio)
    print(f"Audio embedding: {len(audio_emb)} dims, first 5: {audio_emb[:5]}")

    # Mixed multimodal embedding (text + image in one call)
    mixed_emb = embedder.get_embedding(["A red square image", image])
    print(f"Multimodal embedding: {len(mixed_emb)} dims, first 5: {mixed_emb[:5]}")

    # Knowledge base insertion
    await knowledge.ainsert(path="cookbook/07_knowledge/testing_resources/cv_1.pdf")


if __name__ == "__main__":
    asyncio.run(main())
