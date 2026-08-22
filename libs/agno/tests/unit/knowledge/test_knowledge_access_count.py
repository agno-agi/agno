"""Tests for in-memory access count tracking in Knowledge.

Access counts are tracked in memory during search and flushed to the database
during content updates or via explicit flush_access_counts() call.
"""

import pytest

from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite import SqliteDb
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge


@pytest.fixture
def db():
    return SqliteDb(db_url="sqlite:///:memory:")


@pytest.fixture
def knowledge(db):
    return Knowledge(name="test_knowledge", contents_db=db)


def seed_content(db, content_id, access_count=None):
    row = KnowledgeRow(
        id=content_id,
        name="doc.txt",
        description="Test document",
        access_count=access_count,
    )
    db.upsert_knowledge_content(knowledge_row=row)


class TestAccessCountTracking:
    def test_access_counts_initialized_empty(self):
        knowledge = Knowledge(name="test")
        assert knowledge._access_counts == {}

    def test_track_access_increments_counts(self):
        knowledge = Knowledge(name="test")
        docs = [
            Document(content="doc1", content_id="id-1"),
            Document(content="doc2", content_id="id-2"),
            Document(content="doc3", content_id="id-1"),
        ]
        knowledge._track_access(docs)
        assert knowledge._access_counts == {"id-1": 2, "id-2": 1}

    def test_track_access_ignores_none_content_id(self):
        knowledge = Knowledge(name="test")
        docs = [
            Document(content="doc1", content_id="id-1"),
            Document(content="doc2", content_id=None),
        ]
        knowledge._track_access(docs)
        assert knowledge._access_counts == {"id-1": 1}


class TestFlushAccessCounts:
    def test_flush_persists_to_db(self, db, knowledge):
        seed_content(db, "content-1")

        knowledge._track_access(
            [
                Document(content="chunk one", content_id="content-1"),
                Document(content="chunk two", content_id="content-1"),
            ]
        )
        knowledge._track_access([Document(content="chunk three", content_id="content-1")])

        assert knowledge._access_counts == {"content-1": 3}

        knowledge.flush_access_counts()

        stored = db.get_knowledge_content("content-1")
        assert stored is not None
        assert stored.access_count == 3
        assert stored.updated_at is not None
        assert knowledge._access_counts == {}

    def test_flush_accumulates_onto_existing_count(self, db, knowledge):
        seed_content(db, "content-1", access_count=5)

        knowledge._track_access([Document(content="chunk one", content_id="content-1")])
        knowledge._track_access([Document(content="chunk two", content_id="content-1")])
        knowledge.flush_access_counts()

        stored = db.get_knowledge_content("content-1")
        assert stored.access_count == 7

    def test_flush_keeps_counts_for_unknown_content(self, db, knowledge):
        seed_content(db, "content-1")

        knowledge._track_access(
            [
                Document(content="chunk one", content_id="content-1"),
                Document(content="stale chunk", content_id="deleted-content"),
            ]
        )
        knowledge.flush_access_counts()

        assert db.get_knowledge_content("content-1").access_count == 1
        assert knowledge._access_counts == {"deleted-content": 1}

    def test_flush_noop_when_empty(self, db, knowledge):
        knowledge.flush_access_counts()
        assert knowledge._access_counts == {}

    def test_flush_noop_without_contents_db(self):
        knowledge = Knowledge(name="test")
        knowledge._access_counts = {"id-1": 5}
        knowledge.flush_access_counts()
        assert knowledge._access_counts == {"id-1": 5}
