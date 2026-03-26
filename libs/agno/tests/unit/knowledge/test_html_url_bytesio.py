"""Regression tests: .html/.htm URLs must NOT be wrapped in BytesIO (issue #6985).

For URLs ending in .html or .htm the knowledge loader must pass the URL string
directly to the reader (WebsiteReader) instead of downloading the page into a
BytesIO buffer. The fix adds a ``_web_extensions`` guard in ``_load_from_url``
and ``_aload_from_url``.

See: https://github.com/agno-agi/agno/pull/6991
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.vectordb.base import VectorDb


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubVectorDb(VectorDb):
    """Minimal VectorDb that does nothing."""

    def create(self): ...
    async def async_create(self): ...
    def name_exists(self, name): return False
    async def async_name_exists(self, name): return False
    def id_exists(self, id): return False
    def content_hash_exists(self, content_hash): return False
    def insert(self, content_hash, documents, filters=None): ...
    async def async_insert(self, content_hash, documents, filters=None): ...
    def upsert(self, content_hash, documents, filters=None): ...
    async def async_upsert(self, content_hash, documents, filters=None): ...
    def search(self, query, limit=5, filters=None): return []
    async def async_search(self, query, limit=5, filters=None): return []
    def drop(self): ...
    async def async_drop(self): ...
    def exists(self): return True
    async def async_exists(self): return True
    def delete(self): return True
    def delete_by_id(self, id): return True
    def delete_by_name(self, name): return True
    def delete_by_metadata(self, metadata): return True
    def update_metadata(self, content_id, metadata): ...
    def delete_by_content_id(self, content_id): return True
    def get_supported_search_types(self): return ["vector"]


class _CapturingReader(Reader):
    """Reader that records the source argument it receives."""

    def __init__(self):
        super().__init__()
        self.received_sources: list = []

    @classmethod
    def get_supported_chunking_strategies(cls):
        from agno.knowledge.chunking.strategy import ChunkingStrategyType
        return [ChunkingStrategyType.FIXED_SIZE_CHUNKER]

    @classmethod
    def get_supported_content_types(cls):
        from agno.knowledge.types import ContentType
        return [ContentType.TEXT]

    def read(self, source, name=None, **kwargs) -> List[Document]:
        self.received_sources.append(source)
        return []

    async def async_read(self, source, name=None, **kwargs) -> List[Document]:
        self.received_sources.append(source)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_knowledge(reader: _CapturingReader) -> Knowledge:
    kb = Knowledge(vector_db=_StubVectorDb())
    if kb.readers is None:
        kb.readers = {}
    kb.readers["website"] = reader
    return kb


def _stub_storage(kb: Knowledge, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all persistence methods called inside _load_from_url."""
    monkeypatch.setattr(kb, "_insert_contents_db", lambda content: None)
    monkeypatch.setattr(kb, "_should_skip", lambda content_hash, skip: False)
    monkeypatch.setattr(kb, "_update_content", lambda content: None)
    monkeypatch.setattr(kb, "_chunk_documents_sync", lambda reader, docs: docs)
    monkeypatch.setattr(kb, "_prepare_documents_for_insert", lambda docs, cid, **kw: docs)
    monkeypatch.setattr(kb, "_handle_vector_db_insert", lambda content, docs, upsert: None)


def _stub_async_storage(kb: Knowledge, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all persistence methods called inside _aload_from_url."""
    import asyncio

    async def _anoop(*a, **kw):
        return None

    monkeypatch.setattr(kb, "_ainsert_contents_db", _anoop)
    monkeypatch.setattr(kb, "_should_skip", lambda *a: False)
    monkeypatch.setattr(kb, "_aupdate_content", _anoop)
    monkeypatch.setattr(kb, "_prepare_documents_for_insert", lambda docs, cid, **kw: docs)
    monkeypatch.setattr(kb, "_ahandle_vector_db_insert", _anoop)


# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------


class TestLoadFromUrlHtmlSkipsBytesIO:
    """_load_from_url must NOT create a BytesIO for .html/.htm URLs."""

    def test_html_url_does_not_fetch_and_reader_gets_string(self, monkeypatch):
        """For a .html URL fetch_with_retry must NOT be called and the reader
        must receive the URL as a plain string, not BytesIO."""
        reader = _CapturingReader()
        kb = _make_knowledge(reader)
        _stub_storage(kb, monkeypatch)

        html_url = "https://example.com/page.html"

        fetch_mock = MagicMock(
            side_effect=AssertionError("fetch_with_retry must not be called for .html URLs")
        )
        with patch("agno.utils.http.fetch_with_retry", fetch_mock):
            kb._load_from_url(Content(url=html_url), upsert=True, skip_if_exists=False)

        assert len(reader.received_sources) == 1, "Reader should be called once"
        src = reader.received_sources[0]
        assert isinstance(src, str), f"Expected str, got {type(src).__name__}"
        assert not isinstance(src, BytesIO)
        assert src == html_url

    def test_htm_url_does_not_fetch_and_reader_gets_string(self, monkeypatch):
        """Same as above but for .htm extension."""
        reader = _CapturingReader()
        kb = _make_knowledge(reader)
        _stub_storage(kb, monkeypatch)

        htm_url = "https://example.com/docs/index.htm"

        fetch_mock = MagicMock(
            side_effect=AssertionError("fetch_with_retry must not be called for .htm URLs")
        )
        with patch("agno.utils.http.fetch_with_retry", fetch_mock):
            kb._load_from_url(Content(url=htm_url), upsert=True, skip_if_exists=False)

        assert len(reader.received_sources) == 1
        src = reader.received_sources[0]
        assert isinstance(src, str)
        assert not isinstance(src, BytesIO)

    def test_non_html_extension_uses_bytesio(self, monkeypatch):
        """Sanity check: a .csv URL must still go through BytesIO."""
        reader = _CapturingReader()
        kb = _make_knowledge(reader)
        _stub_storage(kb, monkeypatch)

        # Register the capturing reader for csv extension too
        kb.readers["csv"] = reader

        csv_url = "https://example.com/data.csv"
        fake_response = MagicMock()
        fake_response.content = b"a,b,c\n1,2,3"

        with patch("agno.utils.http.fetch_with_retry", return_value=fake_response):
            kb._load_from_url(Content(url=csv_url), upsert=True, skip_if_exists=False)

        assert len(reader.received_sources) == 1
        src = reader.received_sources[0]
        assert isinstance(src, BytesIO), (
            f"Non-HTML extension (.csv) should use BytesIO but got {type(src).__name__}"
        )

    def test_bare_url_without_extension_passes_string(self, monkeypatch):
        """URLs with no extension should also pass the string (not fetch BytesIO)."""
        reader = _CapturingReader()
        kb = _make_knowledge(reader)
        _stub_storage(kb, monkeypatch)

        bare_url = "https://example.com/about"

        fetch_mock = MagicMock(
            side_effect=AssertionError("fetch_with_retry must not be called for extensionless URLs")
        )
        with patch("agno.utils.http.fetch_with_retry", fetch_mock):
            kb._load_from_url(Content(url=bare_url), upsert=True, skip_if_exists=False)

        assert len(reader.received_sources) == 1
        src = reader.received_sources[0]
        assert isinstance(src, str)


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


class TestALoadFromUrlHtmlSkipsBytesIO:
    """_aload_from_url must NOT create a BytesIO for .html/.htm URLs."""

    @pytest.mark.asyncio
    async def test_html_url_async_reader_gets_string(self, monkeypatch):
        """Async path: .html URL must pass string to reader, not BytesIO."""
        reader = _CapturingReader()
        kb = _make_knowledge(reader)
        _stub_async_storage(kb, monkeypatch)

        html_url = "https://example.com/article.html"

        async def forbidden_fetch(*args, **kwargs):
            raise AssertionError("async_fetch_with_retry must not be called for .html URLs")

        with patch("agno.knowledge.knowledge.async_fetch_with_retry", forbidden_fetch):
            await kb._aload_from_url(Content(url=html_url), upsert=True, skip_if_exists=False)

        assert len(reader.received_sources) == 1
        src = reader.received_sources[0]
        assert isinstance(src, str), f"Expected str, got {type(src).__name__}"
        assert src == html_url
