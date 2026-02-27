"""Tests for content refresh functionality."""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.pipeline.ingestion import IngestionPipeline


@pytest.fixture
def pipeline():
    return IngestionPipeline(
        vector_db=MagicMock(),
        content_store=MagicMock(),
        reader_registry=MagicMock(),
    )


class TestCheckContentChanged:
    def test_file_changed_by_mtime(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original content")
            path = f.name

        # Set updated_at to before the file was written
        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) - 100,
        )

        assert pipeline.check_content_changed(content) is True

        # Clean up
        Path(path).unlink()

    def test_file_not_changed(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content")
            path = f.name

        # Set updated_at to after file was written
        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) + 100,
        )

        assert pipeline.check_content_changed(content) is False

        Path(path).unlink()

    def test_file_does_not_exist(self, pipeline):
        content = Content(
            id="test-id",
            path="/nonexistent/path.txt",
            updated_at=int(time.time()),
        )

        assert pipeline.check_content_changed(content) is False

    def test_url_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value="new_hash"):
            assert pipeline.check_content_changed(content) is True

    def test_url_not_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="same_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value="same_hash"):
            assert pipeline.check_content_changed(content) is False

    def test_url_fetch_failure(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value=None):
            assert pipeline.check_content_changed(content) is False

    def test_no_path_or_url_returns_false(self, pipeline):
        content = Content(id="test-id")
        assert pipeline.check_content_changed(content) is False

    @pytest.mark.asyncio
    async def test_async_file_changed(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content")
            path = f.name

        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) - 100,
        )

        assert await pipeline.acheck_content_changed(content) is True

        Path(path).unlink()

    @pytest.mark.asyncio
    async def test_async_url_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_acompute_url_hash", new_callable=AsyncMock, return_value="new_hash"):
            assert await pipeline.acheck_content_changed(content) is True


class TestComputeUrlHash:
    def test_computes_hash(self, pipeline):
        mock_response = MagicMock()
        mock_response.content = b"test content"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            result = pipeline._compute_url_hash("https://example.com")

        assert result is not None
        assert isinstance(result, str)

    def test_returns_none_on_error(self, pipeline):
        with patch("httpx.Client", side_effect=Exception("Connection failed")):
            result = pipeline._compute_url_hash("https://example.com")

        assert result is None


class TestContentHashPersistence:
    """Test that content_hash is round-tripped through KnowledgeRow."""

    def test_knowledge_row_has_content_hash(self):
        from agno.db.schemas.knowledge import KnowledgeRow

        row = KnowledgeRow(name="test", description="", content_hash="abc123")
        assert row.content_hash == "abc123"

    def test_knowledge_row_content_hash_nullable(self):
        from agno.db.schemas.knowledge import KnowledgeRow

        row = KnowledgeRow(name="test", description="")
        assert row.content_hash is None
