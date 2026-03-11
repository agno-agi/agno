"""
Integration tests for Gemini Embedder (including multimodal support).

These tests require a valid GOOGLE_API_KEY environment variable.

To run these tests:
    GOOGLE_API_KEY='...' pytest libs/agno/tests/integration/embedder/test_gemini_embedder.py -v
"""

import os
from pathlib import Path

import pytest

from agno.knowledge.embedder.google import GeminiEmbedder
from agno.media import Audio, Image, Video


def _has_google_api_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY"))


# Skip all tests if GOOGLE_API_KEY is not set
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


class TestGeminiEmbedderText:
    """Tests for text embedding (regression for existing behavior)."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_text_embedding(self, embedder):
        text = "The quick brown fox jumps over the lazy dog."
        embedding = embedder.get_embedding(text)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_text_embedding_and_usage(self, embedder):
        text = "Test embedding with usage."
        embedding, usage = embedder.get_embedding_and_usage(text)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        # Usage metadata may or may not be returned depending on the model
        if usage is not None:
            assert "billable_character_count" in usage

    def test_embedding_consistency(self, embedder):
        text = "Consistency test"
        emb1 = embedder.get_embedding(text)
        emb2 = embedder.get_embedding(text)

        assert len(emb1) == len(emb2)
        assert all(abs(a - b) < 1e-3 for a, b in zip(emb1, emb2))


class TestGeminiEmbedderImage:
    """Tests for image embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_image_embedding(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_image_embedding_and_usage(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding, usage = embedder.get_image_embedding_and_usage(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderAudio:
    """Tests for audio embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_audio_embedding(self, embedder):
        audio = Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")
        embedding = embedder.get_audio_embedding(audio)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_audio_embedding_and_usage(self, embedder):
        audio = Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")
        embedding, usage = embedder.get_audio_embedding_and_usage(audio)

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderVideo:
    """Tests for video embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_video_embedding(self, embedder):
        video = Video(filepath=RESOURCES / "sample.mp4", mime_type="video/mp4")
        embedding = embedder.get_video_embedding(video)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_video_embedding_and_usage(self, embedder):
        video = Video(filepath=RESOURCES / "sample.mp4", mime_type="video/mp4")
        embedding, usage = embedder.get_video_embedding_and_usage(video)

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderMultimodal:
    """Tests for mixed multimodal embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_multimodal_text_and_image(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding = embedder.get_multimodal_embedding(["A red square image", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_multimodal_embedding_and_usage(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding, usage = embedder.get_multimodal_embedding_and_usage(["description", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    def test_multimodal_text_and_audio(self, embedder):
        audio = Audio(filepath=RESOURCES / "sample.wav", mime_type="audio/wav")
        embedding = embedder.get_multimodal_embedding(["A sine wave tone", audio])

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderModelGuard:
    """Tests that multimodal methods reject text-only models and invalid inputs."""

    def test_image_embedding_requires_multimodal_model(self):
        embedder = GeminiEmbedder(id="gemini-embedding-001")
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")

        with pytest.raises(ValueError, match="does not support multimodal"):
            embedder.get_image_embedding(image)

    def test_multimodal_embedding_requires_multimodal_model(self):
        embedder = GeminiEmbedder(id="gemini-embedding-001")

        with pytest.raises(ValueError, match="does not support multimodal"):
            embedder.get_multimodal_embedding(["some text"])

    def test_multimodal_embedding_rejects_plain_string(self):
        embedder = GeminiEmbedder(id=MULTIMODAL_MODEL)

        with pytest.raises(TypeError, match="expects a list of inputs, not a plain string"):
            embedder.get_multimodal_embedding("hello")  # type: ignore[arg-type]

    def test_image_without_mime_type_uses_default(self):
        """Image without mime_type should fall back to image/png default."""
        embedder = GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)
        png_bytes = (RESOURCES / "sample.png").read_bytes()
        image = Image(content=png_bytes)
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    def test_image_mime_inferred_from_filepath(self):
        """MIME type should be inferred from filepath extension when mime_type is not set."""
        image = Image(filepath=RESOURCES / "sample.png")
        embedder = GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderDimensionality:
    """Tests for dimensionality control."""

    def test_dimensionality_control(self):
        for dim in (768, 1536, 3072):
            embedder = GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=dim)
            embedding = embedder.get_embedding("Hello world")
            assert len(embedding) == dim, f"Expected {dim} dims, got {len(embedding)}"


class TestGeminiEmbedderAsync:
    """Tests for async methods."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    @pytest.mark.asyncio
    async def test_async_get_embedding(self, embedder):
        embedding = await embedder.async_get_embedding("Async text embedding test")

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    @pytest.mark.asyncio
    async def test_async_image_embedding(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding = await embedder.async_get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    @pytest.mark.asyncio
    async def test_async_multimodal_embedding(self, embedder):
        image = Image(filepath=RESOURCES / "sample.png", mime_type="image/png")
        embedding = await embedder.async_get_multimodal_embedding(["test text", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768
