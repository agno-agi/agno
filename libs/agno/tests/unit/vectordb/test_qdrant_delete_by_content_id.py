"""Regression tests for #11718: Qdrant delete failures must not orphan points.

Two behaviors used to make ``Knowledge.remove_content_by_id`` delete the content
row while its points stayed in the collection: exceptions were swallowed into a
``False`` return that legacy rows read as "nothing to delete", and a zero count
skipped the delete request entirely even though inserts use ``wait=False``.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qdrant_client.http import models

from agno.db.schemas.knowledge import KnowledgeRow
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.qdrant import Qdrant


@pytest.fixture
def qdrant_db(mock_embedder):
    db = Qdrant(embedder=mock_embedder, collection="test_collection")
    client = Mock()
    client.count.return_value = SimpleNamespace(count=1)
    client.delete.return_value = SimpleNamespace(status=models.UpdateStatus.COMPLETED)
    db._client = client
    return db


def test_zero_count_still_sends_delete(qdrant_db):
    """A zero count can hide an acknowledged-but-unapplied point (wait=False
    inserts); delete-by-filter is idempotent, so it is always sent."""
    qdrant_db.client.count.return_value = SimpleNamespace(count=0)

    assert qdrant_db.delete_by_content_id("c") is True
    qdrant_db.client.delete.assert_called_once()


def test_count_error_propagates_instead_of_returning_false(qdrant_db):
    qdrant_db.client.count.side_effect = OSError("Qdrant unavailable")

    with pytest.raises(OSError, match="Qdrant unavailable"):
        qdrant_db.delete_by_content_id("c")
    qdrant_db.client.delete.assert_not_called()


def test_delete_error_propagates(qdrant_db):
    qdrant_db.client.delete.side_effect = OSError("timeout")

    with pytest.raises(OSError, match="timeout"):
        qdrant_db.delete_by_content_id("c")


def test_non_completed_status_raises(qdrant_db):
    qdrant_db.client.delete.return_value = SimpleNamespace(status=models.UpdateStatus.ACKNOWLEDGED)

    with pytest.raises(RuntimeError, match="Deletion failed"):
        qdrant_db.delete_by_content_id("c")


def _legacy_knowledge(qdrant_db):
    """Knowledge over a legacy content row with no vectors_indexed marker: a
    False return used to read as a zero-match no-op and the row was dropped."""
    database = Mock()
    database.get_knowledge_content.return_value = KnowledgeRow(id="c", name="legacy", description="", metadata={})
    return Knowledge(vector_db=qdrant_db, content_db=database), database


def test_knowledge_keeps_legacy_row_when_delete_fails(qdrant_db):
    knowledge, database = _legacy_knowledge(qdrant_db)
    qdrant_db.client.count.side_effect = OSError("Qdrant unavailable")

    with pytest.raises(OSError, match="Qdrant unavailable"):
        knowledge.remove_content_by_id("c")
    database.delete_knowledge_content.assert_not_called()


def test_knowledge_sends_delete_and_removes_row_on_zero_count(qdrant_db):
    knowledge, database = _legacy_knowledge(qdrant_db)
    qdrant_db.client.count.return_value = SimpleNamespace(count=0)

    assert knowledge.remove_content_by_id("c") is True
    qdrant_db.client.delete.assert_called_once()
    database.delete_knowledge_content.assert_called_once_with("c", user_id=None)
