"""Per-upload chunker options must not leak into the knowledge base's reader."""

import socket
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.os.routers.knowledge import knowledge as routes
from agno.os.routers.knowledge.knowledge import process_content


@dataclass
class _CustomEmbedder(Embedder):
    id: str = "azure-text-embedding-3-small"
    dimensions: int = 4
    calls: List[str] = field(default_factory=list)

    def get_embedding(self, text: str) -> List[float]:
        self.calls.append(text)
        return [0.25, 0.25, 0.25, 0.25]


class _FakeVectorDb:
    def __init__(self, embedder: Optional[Embedder] = None):
        self.embedder = embedder
        self.inserted_docs: List[Any] = []

    def exists(self) -> bool:
        return True

    def upsert_available(self) -> bool:
        return False

    def content_hash_exists(self, content_hash: str, **kwargs: Any) -> bool:
        return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        return None

    async def async_insert(
        self, content_hash: str, documents: List[Any], filters: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        for doc in documents:
            if self.embedder is not None:
                doc.embedding = self.embedder.get_embedding(doc.content)
        self.inserted_docs.extend(documents)


_MULTI_SENTENCE_BYTES = (
    b"Artificial intelligence agents collaborate on software tasks across repositories. "
    b"Semantic chunking groups consecutive sentences that share contextual meaning. "
    b"Database migrations require strict transactional guarantees and version tracking. "
    b"Vector embeddings project natural language paragraphs into dense geometric spaces."
)


def _content():
    return Content(
        name="a.txt",
        file_data=FileData(content=b"hello", type="text/plain", filename="a.txt"),
    )


@pytest.mark.asyncio
async def test_upload_chunker_does_not_mutate_the_knowledge_base_reader(monkeypatch):
    reader = TextReader(name="notes")
    knowledge = Knowledge(name="docs", readers={"notes": reader})
    content = _content()
    original_chunk_size = reader.chunking_strategy.chunk_size

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, "notes", "FixedSizeChunker", 1000, 0)

    # This upload used the requested chunking ...
    assert content.reader.chunking_strategy.chunk_size == 1000
    # ... but the knowledge base's own reader is unchanged for later uploads.
    assert reader.chunking_strategy.chunk_size == original_chunk_size


@pytest.mark.asyncio
async def test_upload_chunker_does_not_replace_the_resolved_default_reader(monkeypatch):
    knowledge = Knowledge(name="docs")
    text_reader = knowledge.text_reader
    content = Content(
        name="a.txt",
        file_data=FileData(content=b"hello", type="text/plain", filename="a.txt"),
        reader=text_reader,
    )
    original_chunk_size = text_reader.chunking_strategy.chunk_size

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, None, "FixedSizeChunker", 512, 0)

    assert content.reader.chunking_strategy.chunk_size == 512
    assert text_reader.chunking_strategy.chunk_size == original_chunk_size


@pytest.mark.asyncio
async def test_semantic_chunker_infers_embedder_from_vector_db_with_reader_id(monkeypatch):
    pytest.importorskip("chonkie")
    from agno.knowledge.chunking.semantic import SemanticChunking

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    content = Content(
        id="c-semantic-1",
        name="notes.txt",
        content_hash="hash-semantic-1",
        file_data=FileData(content=_MULTI_SENTENCE_BYTES, type="text/plain", filename="notes.txt"),
    )

    await process_content(knowledge, content, "text", "SemanticChunker", 60, 0)

    assert content.reader is not None
    assert isinstance(content.reader.chunking_strategy, SemanticChunking)
    assert content.reader.chunking_strategy.embedder is embedder
    assert len(embedder.calls) > 0
    assert len(vector_db.inserted_docs) > 0
    assert content.status != ContentStatus.FAILED


@pytest.mark.asyncio
async def test_semantic_chunker_infers_embedder_without_reader_id(monkeypatch):
    pytest.importorskip("chonkie")
    from agno.knowledge.chunking.semantic import SemanticChunking

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    text_reader = knowledge.text_reader
    assert text_reader is not None
    default_strategy = text_reader.chunking_strategy
    content = Content(
        id="c-semantic-2",
        name="manual.txt",
        content_hash="hash-semantic-2",
        file_data=FileData(content=_MULTI_SENTENCE_BYTES, type="manual"),
    )

    await process_content(knowledge, content, None, "SemanticChunker", 60, 0)

    assert content.reader is not None
    assert isinstance(content.reader.chunking_strategy, SemanticChunking)
    assert content.reader.chunking_strategy.embedder is embedder
    assert len(embedder.calls) > 0
    assert len(vector_db.inserted_docs) > 0
    assert content.status != ContentStatus.FAILED
    assert text_reader.chunking_strategy is default_strategy


@pytest.mark.asyncio
async def test_non_semantic_chunker_does_not_receive_embedder_kwarg(monkeypatch):
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    content = _content()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, None, "FixedSizeChunker", 512, 32)

    assert content.reader is not None
    assert isinstance(content.reader.chunking_strategy, FixedSizeChunking)
    assert content.reader.chunking_strategy.chunk_size == 512
    assert content.reader.chunking_strategy.overlap == 32


@pytest.mark.asyncio
async def test_semantic_chunker_falls_back_to_default_when_vector_db_has_no_embedder(monkeypatch):
    pytest.importorskip("chonkie")
    from agno.knowledge.chunking.semantic import SemanticChunking

    knowledge = Knowledge(name="docs")
    content = _content()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, "text", "SemanticChunker", 256, 0)

    assert content.reader is not None
    assert isinstance(content.reader.chunking_strategy, SemanticChunking)
    assert type(content.reader.chunking_strategy.embedder).__name__ == "OpenAIEmbedder"
    assert content.reader.chunking_strategy.chunk_size == 256


@pytest.mark.asyncio
async def test_semantic_chunker_infers_embedder_for_website_url_without_reader_id(monkeypatch):
    pytest.importorskip("chonkie")
    pytest.importorskip("bs4")
    from agno.knowledge.chunking.semantic import SemanticChunking

    def _forbid_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network forbidden")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _forbid_network)
    url = "https://example.invalid/articles/semantic-chunking"
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    website_reader = knowledge.website_reader
    assert website_reader is not None
    default_strategy = website_reader.chunking_strategy

    async def _fake_crawl(self: Any, target_url: str, starting_depth: int = 1) -> Dict[str, str]:
        return {target_url: _MULTI_SENTENCE_BYTES.decode("utf-8")}

    monkeypatch.setattr(type(website_reader), "async_crawl", _fake_crawl)
    content = Content(
        id="c-url-website",
        name=url,
        content_hash="hash-url-website",
        url=url,
    )

    await process_content(knowledge, content, None, "SemanticChunker", 20, 0)

    assert content.reader is not None
    assert type(content.reader) is type(website_reader)
    assert content.reader is not website_reader
    assert isinstance(content.reader.chunking_strategy, SemanticChunking)
    assert content.reader.chunking_strategy.embedder is embedder
    assert len(vector_db.inserted_docs) >= 2
    assert len(embedder.calls) > len(vector_db.inserted_docs)
    assert content.status != ContentStatus.FAILED
    assert website_reader.chunking_strategy is default_strategy


@pytest.mark.asyncio
async def test_semantic_chunker_infers_embedder_for_extension_url_without_reader_id(monkeypatch):
    pytest.importorskip("chonkie")
    from agno.knowledge.chunking.semantic import SemanticChunking

    def _forbid_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network forbidden")

    async def _fake_fetch(target_url: str, **kwargs: Any) -> Any:
        return SimpleNamespace(content=_MULTI_SENTENCE_BYTES)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _forbid_network)
    monkeypatch.setattr("agno.knowledge.knowledge.async_fetch_with_retry", _fake_fetch)
    url = "https://example.invalid/docs/notes.txt"
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    text_reader = knowledge.text_reader
    assert text_reader is not None
    default_strategy = text_reader.chunking_strategy
    content = Content(
        id="c-url-txt",
        name=url,
        content_hash="hash-url-txt",
        url=url,
    )

    await process_content(knowledge, content, None, "SemanticChunker", 20, 0)

    assert content.reader is not None
    assert isinstance(content.reader, TextReader)
    assert content.reader is not text_reader
    assert isinstance(content.reader.chunking_strategy, SemanticChunking)
    assert content.reader.chunking_strategy.embedder is embedder
    assert len(vector_db.inserted_docs) >= 2
    assert len(embedder.calls) > len(vector_db.inserted_docs)
    assert content.status != ContentStatus.FAILED
    assert text_reader.chunking_strategy is default_strategy


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,reader_attr,required_pkg",
    [
        ("https://example.invalid/guide", "website_reader", "bs4"),
        ("https://example.invalid/report.pdf", "pdf_reader", "pypdf"),
        ("https://example.invalid/sitemap.xml", "sitemap_reader", "bs4"),
    ],
)
async def test_url_upload_chunker_resolves_default_reader_without_mutating_shared_readers(
    monkeypatch, url: str, reader_attr: str, required_pkg: str
):
    pytest.importorskip("chonkie")
    pytest.importorskip(required_pkg)
    from agno.knowledge.chunking.semantic import SemanticChunking

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(name="docs", vector_db=vector_db)
    shared_reader = getattr(knowledge, reader_attr)
    assert shared_reader is not None
    original_strategy = shared_reader.chunking_strategy
    captured: List[Content] = []

    async def _capture_load(loaded_content: Content, *args: Any, **kwargs: Any) -> None:
        captured.append(loaded_content)

    monkeypatch.setattr(knowledge, "_aload_content", _capture_load)
    content = Content(id="c-url-dispatch", name=url, content_hash="hash-url-dispatch", url=url)

    await process_content(knowledge, content, None, "SemanticChunker", 128, 0)

    assert len(captured) == 1
    resolved_reader = captured[0].reader
    assert resolved_reader is not None
    assert type(resolved_reader) is type(shared_reader)
    assert resolved_reader is not shared_reader
    assert isinstance(resolved_reader.chunking_strategy, SemanticChunking)
    assert resolved_reader.chunking_strategy.embedder is embedder
    assert shared_reader.chunking_strategy is original_strategy


def test_http_upload_url_with_semantic_chunker_without_reader_id_completes(tmp_path, monkeypatch):
    pytest.importorskip("chonkie")

    def _forbid_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network forbidden")

    async def _fake_fetch(target_url: str, **kwargs: Any) -> Any:
        return SimpleNamespace(content=_MULTI_SENTENCE_BYTES)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _forbid_network)
    monkeypatch.setattr("agno.knowledge.knowledge.async_fetch_with_retry", _fake_fetch)

    embedder = _CustomEmbedder()
    vector_db = _FakeVectorDb(embedder=embedder)
    knowledge = Knowledge(
        name="docs",
        contents_db=SqliteDb(db_file=str(tmp_path / "url_chunker.db")),
        vector_db=vector_db,
    )
    text_reader = knowledge.text_reader
    assert text_reader is not None
    default_strategy = text_reader.chunking_strategy

    app = FastAPI()
    app.include_router(routes.get_knowledge_router([knowledge]))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/knowledge/content",
            data={
                "url": "https://example.invalid/docs/notes.txt",
                "chunker": "SemanticChunker",
                "chunk_size": "20",
                "chunk_overlap": "0",
            },
        )
        assert response.status_code == 202, response.text
        content_id = response.json()["id"]
        status_resp = client.get(f"/knowledge/content/{content_id}/status")

    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"
    assert len(vector_db.inserted_docs) >= 2
    assert len(embedder.calls) > len(vector_db.inserted_docs)
    assert text_reader.chunking_strategy is default_strategy
