"""Tests for enrichment_model description generation."""

from dataclasses import dataclass
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.pipeline.ingestion import IngestionPipeline


@dataclass
class MockModelResponse:
    content: Optional[str] = None


class MockModel:
    """Mock model that returns a fixed description."""

    def __init__(self, description: str = "A test document about important topics"):
        self._description = description

    def response(self, messages=None, **kwargs):
        return MockModelResponse(content=self._description)

    async def aresponse(self, messages=None, **kwargs):
        return MockModelResponse(content=self._description)


class MockFailingModel:
    """Mock model that raises an exception."""

    def response(self, messages=None, **kwargs):
        raise RuntimeError("Model unavailable")

    async def aresponse(self, messages=None, **kwargs):
        raise RuntimeError("Model unavailable")


@pytest.fixture
def pipeline():
    return IngestionPipeline(
        vector_db=MagicMock(),
        content_store=MagicMock(),
        reader_registry=MagicMock(),
    )


@pytest.fixture
def documents():
    return [
        Document(content="This is a report about quarterly financials."),
        Document(content="Revenue grew by 15% year over year."),
    ]


@pytest.fixture
def content():
    return Content(
        id="test-id",
        name="Q4 Report",
        description=None,
        status=ContentStatus.PROCESSING,
    )


class TestGenerateDescription:
    def test_generates_description(self, pipeline, documents, content):
        pipeline.enrichment_model = MockModel("Quarterly financial report with revenue analysis")
        result = pipeline._generate_description(content, documents)
        assert result == "Quarterly financial report with revenue analysis"

    def test_truncates_long_description(self, pipeline, documents, content):
        long_desc = "x" * 300
        pipeline.enrichment_model = MockModel(long_desc)
        result = pipeline._generate_description(content, documents)
        assert len(result) == 200

    def test_returns_empty_on_failure(self, pipeline, documents, content):
        pipeline.enrichment_model = MockFailingModel()
        result = pipeline._generate_description(content, documents)
        assert result == ""

    def test_uses_document_name_in_prompt(self, pipeline, content):
        pipeline.enrichment_model = MockModel("test")
        docs = [Document(content="sample text")]
        with patch.object(pipeline.enrichment_model, "response", wraps=pipeline.enrichment_model.response) as mock_resp:
            pipeline._generate_description(content, docs)
            call_args = mock_resp.call_args
            messages = call_args[1].get("messages") or call_args[0][0]
            user_msg = next(m for m in messages if m.role == "user")
            assert "Q4 Report" in user_msg.content

    @pytest.mark.asyncio
    async def test_async_generates_description(self, pipeline, documents, content):
        pipeline.enrichment_model = MockModel("Async description result")
        result = await pipeline._agenerate_description(content, documents)
        assert result == "Async description result"

    @pytest.mark.asyncio
    async def test_async_returns_empty_on_failure(self, pipeline, documents, content):
        pipeline.enrichment_model = MockFailingModel()
        result = await pipeline._agenerate_description(content, documents)
        assert result == ""


class TestEnrichmentInHandleVectorDbInsert:
    """Test that enrichment is called at the right time in handle_vector_db_insert."""

    def test_enrichment_called_when_no_description(self, pipeline, documents):
        content = Content(id="test-id", name="test", description=None, status=ContentStatus.PROCESSING)
        pipeline.enrichment_model = MockModel("Generated description")

        mock_vdb = MagicMock()
        mock_vdb.upsert_available.return_value = True
        pipeline.vector_db = mock_vdb

        mock_store = MagicMock()
        pipeline.content_store = mock_store

        pipeline.handle_vector_db_insert(content, documents, upsert=True)

        assert content.description == "Generated description"
        assert content.status == ContentStatus.COMPLETED

    def test_enrichment_skipped_when_description_exists(self, pipeline, documents):
        content = Content(
            id="test-id", name="test", description="User-provided description", status=ContentStatus.PROCESSING
        )
        pipeline.enrichment_model = MockModel("Should not be used")

        mock_vdb = MagicMock()
        mock_vdb.upsert_available.return_value = True
        pipeline.vector_db = mock_vdb

        mock_store = MagicMock()
        pipeline.content_store = mock_store

        pipeline.handle_vector_db_insert(content, documents, upsert=True)

        assert content.description == "User-provided description"

    def test_enrichment_skipped_when_no_model(self, pipeline, documents):
        content = Content(id="test-id", name="test", description=None, status=ContentStatus.PROCESSING)
        pipeline.enrichment_model = None

        mock_vdb = MagicMock()
        mock_vdb.upsert_available.return_value = True
        pipeline.vector_db = mock_vdb

        mock_store = MagicMock()
        pipeline.content_store = mock_store

        pipeline.handle_vector_db_insert(content, documents, upsert=True)

        assert content.description is None

    @pytest.mark.asyncio
    async def test_async_enrichment_called_when_no_description(self, pipeline, documents):
        content = Content(id="test-id", name="test", description=None, status=ContentStatus.PROCESSING)
        pipeline.enrichment_model = MockModel("Async generated")

        mock_vdb = MagicMock()
        mock_vdb.upsert_available.return_value = True
        mock_vdb.async_upsert = AsyncMock()
        pipeline.vector_db = mock_vdb

        mock_store = MagicMock()
        mock_store.aupdate = AsyncMock()
        pipeline.content_store = mock_store

        await pipeline.ahandle_vector_db_insert(content, documents, upsert=True)

        assert content.description == "Async generated"
        assert content.status == ContentStatus.COMPLETED
