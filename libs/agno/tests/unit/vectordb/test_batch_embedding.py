"""Tests for batch embedding support in Embedder base class and PgVector sync insert/upsert."""

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder

# ========== Embedder base class tests ==========


class ConcreteEmbedder(Embedder):
    """Concrete embedder for testing that tracks calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.individual_call_count = 0

    def get_embedding(self, text: str) -> List[float]:
        self.individual_call_count += 1
        return [0.1] * (self.dimensions or 1536)

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        self.individual_call_count += 1
        return [0.1] * (self.dimensions or 1536), {"prompt_tokens": len(text), "total_tokens": len(text)}


class BatchEmbedder(ConcreteEmbedder):
    """Embedder with native batch support that tracks batch calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.batch_call_count = 0

    def get_embeddings_batch_and_usage(self, texts: List[str]) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        self.batch_call_count += 1
        dims = self.dimensions or 1536
        embeddings = [[0.1] * dims for _ in texts]
        usages: List[Optional[Dict[str, Any]]] = [{"prompt_tokens": len(t), "total_tokens": len(t)} for t in texts]
        return embeddings, usages


def test_base_embedder_has_batch_method():
    """Embedder base class should have get_embeddings_batch_and_usage method."""
    embedder = ConcreteEmbedder()
    assert hasattr(embedder, "get_embeddings_batch_and_usage")


def test_base_embedder_batch_fallback_calls_individual():
    """Default batch implementation should fall back to individual calls."""
    embedder = ConcreteEmbedder(dimensions=4)
    texts = ["hello", "world", "test"]

    embeddings, usages = embedder.get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert len(usages) == 3
    assert embedder.individual_call_count == 3
    for emb in embeddings:
        assert len(emb) == 4
    for usage in usages:
        assert usage is not None
        assert "prompt_tokens" in usage


def test_base_embedder_batch_single_text():
    """Batch method should work with a single text."""
    embedder = ConcreteEmbedder(dimensions=4)

    embeddings, usages = embedder.get_embeddings_batch_and_usage(["single"])

    assert len(embeddings) == 1
    assert len(usages) == 1
    assert embedder.individual_call_count == 1


def test_base_embedder_batch_empty_list():
    """Batch method should handle empty list."""
    embedder = ConcreteEmbedder(dimensions=4)

    embeddings, usages = embedder.get_embeddings_batch_and_usage([])

    assert len(embeddings) == 0
    assert len(usages) == 0
    assert embedder.individual_call_count == 0


def test_subclass_batch_method_is_used():
    """When a subclass provides get_embeddings_batch_and_usage, it should be used."""
    embedder = BatchEmbedder(dimensions=4, enable_batch=True)
    texts = ["hello", "world", "test"]

    embeddings, usages = embedder.get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert len(usages) == 3
    assert embedder.batch_call_count == 1
    assert embedder.individual_call_count == 0


def test_document_embed_sets_embedding():
    """Document.embed should set embedding and usage from embedder."""
    embedder = ConcreteEmbedder(dimensions=4)
    doc = Document(content="test content", name="test")

    doc.embed(embedder=embedder)

    assert doc.embedding is not None
    assert len(doc.embedding) == 4
    assert doc.usage is not None
    assert embedder.individual_call_count == 1


def test_document_already_embedded_skipped_by_check():
    """Pre-embedded documents should be detected by checking embedding is not None."""
    doc = Document(
        content="test",
        name="test",
        embedding=[0.5, 0.5, 0.5, 0.5],
        usage={"prompt_tokens": 1},
    )

    # Simulate the pattern used in _get_document_record:
    # if doc.embedding is None: doc.embed(embedder=...)
    embedder = ConcreteEmbedder(dimensions=4)
    if doc.embedding is None:
        doc.embed(embedder=embedder)

    # Should NOT have been called since embedding already exists
    assert embedder.individual_call_count == 0
    assert doc.embedding == [0.5, 0.5, 0.5, 0.5]


# ========== PgVector batch embedding tests (require sqlalchemy) ==========

try:
    import sqlalchemy  # noqa: F401

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


@pytest.fixture
def mock_pgvector_for_batch():
    """Create a PgVector instance with mocked dependencies for batch embedding tests."""
    pytest.importorskip("sqlalchemy", reason="sqlalchemy not installed")
    from sqlalchemy.engine import URL, Engine

    mock_engine = MagicMock(spec=Engine)
    url = MagicMock(spec=URL)
    url.get_backend_name.return_value = "postgresql"
    mock_engine.url = url
    mock_engine.inspect = MagicMock(return_value=MagicMock())

    embedder = BatchEmbedder(dimensions=4, enable_batch=True)

    with patch("agno.vectordb.pgvector.pgvector.inspect") as mock_inspect:
        inspector = MagicMock()
        inspector.has_table.return_value = False
        mock_inspect.return_value = inspector

        with patch("agno.vectordb.pgvector.pgvector.scoped_session") as mock_scoped_session:
            mock_session_factory = MagicMock()
            mock_scoped_session.return_value = mock_session_factory
            mock_session_instance = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = mock_session_instance

            with patch("agno.vectordb.pgvector.pgvector.Vector"):
                from agno.vectordb.pgvector import PgVector

                db = PgVector(
                    table_name="test_batch_vectors",
                    schema="test_schema",
                    db_engine=mock_engine,
                    embedder=embedder,
                )
                db.table = MagicMock()
                db.table.fullname = "test_schema.test_batch_vectors"
                db.Session = mock_session_factory

                yield db, embedder


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
def test_embed_documents_uses_batch_when_enabled(mock_pgvector_for_batch):
    """_embed_documents should use batch embedding when embedder has enable_batch=True."""
    db, embedder = mock_pgvector_for_batch
    docs = [
        Document(content="doc 1", name="d1"),
        Document(content="doc 2", name="d2"),
        Document(content="doc 3", name="d3"),
    ]

    db._embed_documents(docs)

    # Batch method should have been called once
    assert embedder.batch_call_count == 1
    # Individual calls should not have been made
    assert embedder.individual_call_count == 0
    # All documents should now have embeddings
    for doc in docs:
        assert doc.embedding is not None
        assert len(doc.embedding) == 4
        assert doc.usage is not None


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
def test_embed_documents_individual_when_batch_disabled(mock_pgvector_for_batch):
    """_embed_documents should use individual embedding when enable_batch=False."""
    db, embedder = mock_pgvector_for_batch
    embedder.enable_batch = False

    docs = [
        Document(content="doc 1", name="d1"),
        Document(content="doc 2", name="d2"),
    ]

    db._embed_documents(docs)

    # Batch method should NOT have been called
    assert embedder.batch_call_count == 0
    # Individual calls should have been made (2 docs)
    assert embedder.individual_call_count == 2
    # All documents should now have embeddings
    for doc in docs:
        assert doc.embedding is not None


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
def test_get_document_record_skips_embed_when_already_embedded(mock_pgvector_for_batch):
    """_get_document_record should not re-embed if document already has an embedding."""
    db, embedder = mock_pgvector_for_batch

    doc = Document(
        id="test-id",
        content="already embedded content",
        name="test_doc",
        embedding=[0.5] * 4,
        usage={"prompt_tokens": 5, "total_tokens": 5},
    )

    record = db._get_document_record(doc, filters=None, content_hash="test_hash")

    # Embedding should remain unchanged
    assert record["embedding"] == [0.5] * 4
    # No individual calls should have been made
    assert embedder.individual_call_count == 0
    assert embedder.batch_call_count == 0


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
def test_insert_uses_batch_embedding(mock_pgvector_for_batch):
    """Insert should batch embed documents before building records."""
    db, embedder = mock_pgvector_for_batch

    docs = [
        Document(id="d1", content="content 1", name="doc_1"),
        Document(id="d2", content="content 2", name="doc_2"),
        Document(id="d3", content="content 3", name="doc_3"),
    ]

    sess = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = sess
    db.Session.return_value = cm

    with patch("agno.vectordb.pgvector.pgvector.postgresql.insert") as mock_insert:
        insert_stmt_sentinel = object()
        mock_insert.return_value = insert_stmt_sentinel

        db.insert(content_hash="test_hash", documents=docs)

        # Batch embedding should be called once (all 3 docs in one batch)
        assert embedder.batch_call_count == 1
        assert embedder.individual_call_count == 0

        # All records should have been inserted
        args, kwargs = sess.execute.call_args
        batch_records = args[1]
        assert len(batch_records) == 3

        # Each record should have an embedding
        for record in batch_records:
            assert record["embedding"] is not None
            assert len(record["embedding"]) == 4


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
def test_upsert_uses_batch_embedding(mock_pgvector_for_batch):
    """Upsert should batch embed documents before building records."""
    db, embedder = mock_pgvector_for_batch

    docs = [
        Document(id="d1", content="content 1", name="doc_1"),
        Document(id="d2", content="content 2", name="doc_2"),
    ]

    sess = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = sess
    db.Session.return_value = cm

    with patch("agno.vectordb.pgvector.pgvector.postgresql.insert") as mock_insert:
        insert_stmt = MagicMock(name="insert_stmt")
        after_values = MagicMock(name="after_values")
        after_values.excluded = MagicMock(name="excluded")
        upsert_stmt = object()

        mock_insert.return_value = insert_stmt
        insert_stmt.values.return_value = after_values
        after_values.on_conflict_do_update.return_value = upsert_stmt

        with patch.object(db, "content_hash_exists", return_value=False):
            db.upsert(content_hash="test_hash", documents=docs)

        # Batch embedding should be called once
        assert embedder.batch_call_count == 1
        assert embedder.individual_call_count == 0

        # Records should have been created
        assert insert_stmt.values.called
        (values_arg,), _ = insert_stmt.values.call_args
        assert len(values_arg) == 2
        for record in values_arg:
            assert record["embedding"] is not None
