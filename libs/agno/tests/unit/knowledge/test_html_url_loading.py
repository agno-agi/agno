"""Tests for fix: _load_from_url must not pass BytesIO to WebsiteReader for .html URLs.

Regression tests for https://github.com/agno-agi/agno/issues/6985.

When a URL path ends in a web-content extension (.html, .htm, .xhtml),
_load_from_url and _aload_from_url were incorrectly fetching the page
into a BytesIO object and passing that to the reader. WebsiteReader
expects a plain URL string, causing:

    AttributeError: '_io.BytesIO' object has no attribute 'decode'
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Minimal VectorDb stub."""

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def search(self, query: str, limit: int = 5, filters=None):
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None):
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self):
        return ["vector"]


class CaptureSourceReader(Reader):
    """Test reader that records the source argument it receives."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.received_source = None

    @classmethod
    def get_supported_chunking_strategies(cls):
        from agno.knowledge.chunking.strategy import ChunkingStrategyType

        return [ChunkingStrategyType.FIXED_SIZE_CHUNKER]

    @classmethod
    def get_supported_content_types(cls):
        from agno.knowledge.types import ContentType

        return [ContentType.TXT]

    def read(self, source, name=None, **kwargs):
        self.received_source = source
        return []

    async def async_read(self, source, name=None, **kwargs):
        self.received_source = source
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_knowledge(reader: Reader) -> Knowledge:
    knowledge = Knowledge(vector_db=MockVectorDb())
    # website_reader is a lazy property via _get_reader; patch it directly
    knowledge._get_reader = lambda _kind: reader  # type: ignore[method-assign]
    return knowledge


# ---------------------------------------------------------------------------
# Sync path (_load_from_url)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://nmap.org/book/man.html",
        "https://example.com/page.htm",
        "https://example.com/doc.xhtml",
    ],
)
def test_load_from_url_html_passes_url_string_not_bytesio(url):
    """For .html/.htm/.xhtml URLs the reader must receive the URL string, never a BytesIO."""
    reader = CaptureSourceReader()
    knowledge = _make_knowledge(reader)

    from agno.knowledge.knowledge import Content

    content = Content(url=url)

    # Patch the DB/skip/vector-insert helpers so only the reader path runs
    with (
        patch.object(knowledge, "_insert_contents_db"),
        patch.object(knowledge, "_should_skip", return_value=False),
        patch.object(knowledge, "_update_content"),
        patch.object(knowledge, "_handle_vector_db_insert"),
        patch.object(knowledge, "_chunk_documents_sync", side_effect=lambda _r, docs: docs),
    ):
        knowledge._load_from_url(content, upsert=True, skip_if_exists=False)

    assert reader.received_source is not None, "Reader was never called"
    assert not isinstance(reader.received_source, BytesIO), f"Reader received BytesIO instead of URL string for {url}"
    assert isinstance(reader.received_source, str), f"Expected str, got {type(reader.received_source)} for {url}"


def test_load_from_url_pdf_still_uses_bytesio():
    """Non-web extensions (e.g. .pdf) must still go through the BytesIO path."""
    reader = CaptureSourceReader()
    knowledge = _make_knowledge(reader)

    from agno.knowledge.knowledge import Content

    content = Content(url="https://example.com/report.pdf")

    mock_response = MagicMock()
    mock_response.content = b"%PDF-fake"

    with (
        patch.object(knowledge, "_insert_contents_db"),
        patch.object(knowledge, "_should_skip", return_value=False),
        patch.object(knowledge, "_update_content"),
        patch.object(knowledge, "_handle_vector_db_insert"),
        patch.object(knowledge, "_chunk_documents_sync", side_effect=lambda _r, docs: docs),
        patch("agno.utils.http.fetch_with_retry", return_value=mock_response),
        patch.object(knowledge, "_select_reader_by_extension", return_value=(reader, "report.pdf")),
    ):
        knowledge._load_from_url(content, upsert=True, skip_if_exists=False)

    assert isinstance(reader.received_source, BytesIO), "PDF should still use BytesIO path"


# ---------------------------------------------------------------------------
# Async path (_aload_from_url)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://nmap.org/book/man.html",
        "https://example.com/page.htm",
        "https://example.com/doc.xhtml",
    ],
)
async def test_aload_from_url_html_passes_url_string_not_bytesio(url):
    """Async path: for .html/.htm/.xhtml URLs the reader must receive the URL string."""
    reader = CaptureSourceReader()
    knowledge = _make_knowledge(reader)

    from agno.knowledge.knowledge import Content

    content = Content(url=url)

    with (
        patch.object(knowledge, "_ainsert_contents_db", new_callable=AsyncMock),
        patch.object(knowledge, "_should_skip", return_value=False),
        patch.object(knowledge, "_aupdate_content", new_callable=AsyncMock),
        patch.object(knowledge, "_ahandle_vector_db_insert", new_callable=AsyncMock),
    ):
        await knowledge._aload_from_url(content, upsert=True, skip_if_exists=False)

    assert reader.received_source is not None, "Reader was never called"
    assert not isinstance(reader.received_source, BytesIO), (
        f"Async reader received BytesIO instead of URL string for {url}"
    )
    assert isinstance(reader.received_source, str), f"Expected str, got {type(reader.received_source)} for {url}"
