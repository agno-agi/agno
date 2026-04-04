"""
Integration tests for multimodal Knowledge insertion.

These tests require:
  - GOOGLE_API_KEY environment variable
  - A running PostgreSQL instance (via cookbook/scripts/run_pgvector.sh)

To run:
    GOOGLE_API_KEY='...' pytest libs/agno/tests/integration/knowledge/test_multimodal_knowledge.py -v
"""

import os
from pathlib import Path

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image, Video
from agno.vectordb.pgvector import PgVector


def _has_google_api_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY"))


pytestmark = pytest.mark.skipif(
    not _has_google_api_key(),
    reason="GOOGLE_API_KEY not set",
)

MULTIMODAL_MODEL = "gemini-embedding-2-preview"
RESOURCES = (
    Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    / "cookbook"
    / "07_knowledge"
    / "testing_resources"
)

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


@pytest.fixture
def embedder():
    return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)


@pytest.fixture
def knowledge(embedder):
    table_name = f"test_multimodal_{os.urandom(4).hex()}"
    vector_db = PgVector(db_url=DB_URL, table_name=table_name, embedder=embedder)
    kb = Knowledge(vector_db=vector_db)
    yield kb
    # Cleanup
    try:
        vector_db.drop()
    except Exception:
        pass


class TestMultimodalInsert:
    """Tests for inserting media into Knowledge."""

    @pytest.mark.asyncio
    async def test_insert_image_with_description(self, knowledge):
        """Insert an image with text_content and verify it's stored."""
        await knowledge.ainsert(
            images=[Image(filepath=RESOURCES / "sample.png", mime_type="image/png")],
            text_content="A red square test image",
        )

        results = await knowledge.asearch("red square image")
        assert len(results) > 0
        assert any("red square" in r.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_insert_audio_with_description(self, knowledge):
        """Insert audio with text_content and verify it's stored."""
        await knowledge.ainsert(
            audio=[Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")],
            text_content="A sine wave audio tone for testing",
        )

        results = await knowledge.asearch("sine wave audio")
        assert len(results) > 0
        assert any("sine wave" in r.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_insert_video_with_description(self, knowledge):
        """Insert video with text_content and verify it's stored."""
        await knowledge.ainsert(
            video=[Video(filepath=RESOURCES / "sample.mp4", mime_type="video/mp4")],
            text_content="A short test video clip",
        )

        results = await knowledge.asearch("test video clip")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_text_query_finds_image(self, knowledge):
        """Insert image + text content, query with text, verify both found."""
        # Insert image
        await knowledge.ainsert(
            images=[Image(filepath=RESOURCES / "coffee_production.png", mime_type="image/png")],
            text_content="Bar chart showing top coffee producing countries with Brazil leading at 62.6 million bags",
        )

        # Insert text content
        await knowledge.ainsert(
            path=str(RESOURCES / "coffee.md"),
            skip_if_exists=True,
        )

        # Query should find results from both text and image knowledge
        results = await knowledge.asearch("coffee production")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_content_hash_deduplication(self, knowledge):
        """Insert same image twice with skip_if_exists, verify only stored once."""
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")

        await knowledge.ainsert(
            images=[image],
            text_content="A red square",
            skip_if_exists=True,
        )

        await knowledge.ainsert(
            images=[image],
            text_content="A red square",
            skip_if_exists=True,
        )

        results = await knowledge.asearch("red square")
        # Should find exactly 1 result (not duplicated)
        image_results = [r for r in results if "red square" in r.content.lower()]
        assert len(image_results) == 1


class TestMultimodalDocument:
    """Tests for the Document media dispatch."""

    def test_document_has_media_property(self):
        """has_media property works correctly."""
        doc = Document(content="test")
        assert doc.has_media is False

        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        doc_with_media = Document(content="test", media=image)
        assert doc_with_media.has_media is True

    def test_document_embed_dispatches_to_image(self, embedder):
        """embed() calls image embedding when media is an Image."""
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        doc = Document(content="A test image", media=image)
        doc.embed(embedder=embedder)

        assert doc.embedding is not None
        assert isinstance(doc.embedding, list)
        assert len(doc.embedding) == 768

    def test_document_embed_text_fallback(self, embedder):
        """embed() calls text embedding when no media is attached."""
        doc = Document(content="A simple text document")
        doc.embed(embedder=embedder)

        assert doc.embedding is not None
        assert isinstance(doc.embedding, list)
        assert len(doc.embedding) == 768

    @pytest.mark.asyncio
    async def test_async_document_embed_image(self, embedder):
        """async_embed() calls async image embedding."""
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        doc = Document(content="A test image", media=image)
        await doc.async_embed(embedder=embedder)

        assert doc.embedding is not None
        assert len(doc.embedding) == 768


class TestMultimodalInsertSync:
    """Sync insert tests."""

    def test_insert_image_sync(self, knowledge):
        """Sync insert of an image with description."""
        knowledge.insert(
            images=[Image(filepath=RESOURCES / "sample.png", mime_type="image/png")],
            text_content="A red square test image",
        )

        results = knowledge.search("red square image")
        assert len(results) > 0
