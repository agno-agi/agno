"""
Integration tests for Gemini Embedder (including multimodal support).

These tests require a valid GOOGLE_API_KEY environment variable.

To run these tests:
    GOOGLE_API_KEY='...' pytest libs/agno/tests/integration/embedder/test_gemini_embedder.py -v
"""

import io
import math
import os
import struct
import zlib

import pytest

from agno.knowledge.embedder.google import GeminiEmbedder
from agno.media import Audio, Image


def _has_google_api_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY"))


def _generate_test_png(width: int = 64, height: int = 64) -> bytes:
    """Generate a minimal valid PNG (red square) in memory."""

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw_rows = b""
    for _ in range(height):
        raw_rows += b"\x00"  # filter byte
        for _ in range(width):
            raw_rows += b"\xff\x00\x00"  # RGB red
    compressed = zlib.compress(raw_rows)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    return png


def _generate_wav_bytes(duration_s: float = 1.0, freq: int = 440, sample_rate: int = 16000) -> bytes:
    """Generate a simple sine-wave WAV in memory."""
    num_samples = int(sample_rate * duration_s)
    buf = io.BytesIO()
    data_size = num_samples * 2  # 16-bit mono
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    for i in range(num_samples):
        sample = int(32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        buf.write(struct.pack("<h", sample))
    return buf.getvalue()


# Skip all tests if GOOGLE_API_KEY is not set
pytestmark = pytest.mark.skipif(
    not _has_google_api_key(),
    reason="GOOGLE_API_KEY not set",
)

MULTIMODAL_MODEL = "gemini-embedding-2-preview"


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
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_image_embedding_and_usage(self, embedder):
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding, usage = embedder.get_image_embedding_and_usage(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderAudio:
    """Tests for audio embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_audio_embedding(self, embedder):
        wav_bytes = _generate_wav_bytes()
        audio = Audio(content=wav_bytes, mime_type="audio/wav")
        embedding = embedder.get_audio_embedding(audio)

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)


class TestGeminiEmbedderMultimodal:
    """Tests for mixed multimodal embedding."""

    @pytest.fixture
    def embedder(self):
        return GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)

    def test_multimodal_text_and_image(self, embedder):
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding = embedder.get_multimodal_embedding(["A red square image", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)

    def test_multimodal_embedding_and_usage(self, embedder):
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding, usage = embedder.get_multimodal_embedding_and_usage(["description", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768


class TestGeminiEmbedderModelGuard:
    """Tests that multimodal methods reject text-only models."""

    def test_image_embedding_requires_multimodal_model(self):
        embedder = GeminiEmbedder(id="gemini-embedding-001")
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")

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
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes)
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    def test_image_mime_inferred_from_filepath(self):
        """MIME type should be inferred from filepath extension when mime_type is not set."""
        import os
        import tempfile

        png_bytes = _generate_test_png()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes)
            tmp_path = f.name

        image = Image(filepath=tmp_path)
        embedder = GeminiEmbedder(id=MULTIMODAL_MODEL, dimensions=768)
        embedding = embedder.get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768

        os.unlink(tmp_path)


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
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding = await embedder.async_get_image_embedding(image)

        assert isinstance(embedding, list)
        assert len(embedding) == 768

    @pytest.mark.asyncio
    async def test_async_multimodal_embedding(self, embedder):
        png_bytes = _generate_test_png()
        image = Image(content=png_bytes, mime_type="image/png")
        embedding = await embedder.async_get_multimodal_embedding(["test text", image])

        assert isinstance(embedding, list)
        assert len(embedding) == 768
