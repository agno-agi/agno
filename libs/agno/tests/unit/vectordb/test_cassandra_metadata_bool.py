"""Boolean metadata criteria must match in Cassandra.delete_by_metadata.

insert()/update_metadata() store every metadata value with str(), so `True` lands
in metadata_s as "True". _metadata_matches compared a bool criterion against the
stored value as-is, so `row_metadata[key] != value` was `"True" != True` for every
boolean criterion: the row never matched and delete_by_metadata silently reported
nothing deleted. The non-boolean branch already stringified before comparing.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agno.knowledge.document import Document
from agno.vectordb.cassandra import Cassandra
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable


class FakeSession:
    """Records SELECTs against the fixture rows and DELETEs against the table."""

    def __init__(self, rows):
        self.rows = rows
        self.deleted = []

    def execute(self, query, params=None):
        if query.lstrip().upper().startswith("SELECT"):
            return list(self.rows)
        self.deleted.append(params)
        return None


def build_vector_db(mock_embedder, rows=()):
    session = FakeSession(list(rows))
    table_name = f"test_vectors_bool_{uuid.uuid4().hex[:8]}"
    with patch.object(AgnoMetadataVectorCassandraTable, "__new__", return_value=MagicMock()):
        db = Cassandra(
            table_name=table_name,
            keyspace="test_vectordb",
            embedder=mock_embedder,
            session=session,
        )
    db.session = session
    return db, session


class TestWritePathStringifies:
    """What agno itself stores, so the matcher's input is never guesswork."""

    def test_insert_stores_metadata_as_strings(self, mock_embedder):
        db, _ = build_vector_db(mock_embedder)
        db.insert(
            content_hash="hash-1",
            documents=[Document(id="d1", name="doc", content="hello", meta_data={"flag": True, "page": 3})],
            filters={"archived": False},
            user_id="u1",
        )
        stored = db.table.put_async.call_args.kwargs["metadata"]
        assert stored["flag"] == "True"
        assert stored["page"] == "3"
        assert stored["archived"] == "False"


class TestMetadataMatchesBoolean:
    def test_matches_the_values_the_write_path_produced(self, mock_embedder):
        db, _ = build_vector_db(mock_embedder)
        stored = {"flag": "True", "archived": "False", "page": "3"}
        assert db._metadata_matches(stored, {"flag": True}) is True
        assert db._metadata_matches(stored, {"archived": False}) is True

    def test_matches_a_native_bool_row_from_another_writer(self, mock_embedder):
        db, _ = build_vector_db(mock_embedder)
        assert db._metadata_matches({"flag": True}, {"flag": True}) is True
        assert db._metadata_matches({"flag": False}, {"flag": False}) is True

    def test_still_rejects_a_differing_value(self, mock_embedder):
        """The fix must not turn every criterion into a match."""
        db, _ = build_vector_db(mock_embedder)
        stored = {"flag": "True", "archived": "False", "page": "3"}
        assert db._metadata_matches(stored, {"flag": False}) is False
        assert db._metadata_matches(stored, {"archived": True}) is False
        assert db._metadata_matches(stored, {"page": 4}) is False
        assert db._metadata_matches(stored, {"missing": True}) is False
        assert db._metadata_matches(stored, {"flag": True, "page": 4}) is False

    def test_non_boolean_criteria_keep_matching_as_before(self, mock_embedder):
        db, _ = build_vector_db(mock_embedder)
        stored = {"flag": "True", "page": "7", "name": "docs"}
        assert db._metadata_matches(stored, {"page": 7}) is True
        assert db._metadata_matches(stored, {"name": "docs"}) is True


class TestDeleteByMetadata:
    def test_deletes_for_a_boolean_criterion(self, mock_embedder):
        row = SimpleNamespace(row_id="r1", metadata_s={"flag": "True", "content_id": "c1"})
        db, session = build_vector_db(mock_embedder, rows=[row])

        assert db.delete_by_metadata({"flag": True}) is True
        assert session.deleted, "the row the criterion matches must actually be deleted"

    def test_reports_nothing_deleted_for_a_non_matching_boolean(self, mock_embedder):
        row = SimpleNamespace(row_id="r2", metadata_s={"flag": "True", "content_id": "c1"})
        db, session = build_vector_db(mock_embedder, rows=[row])

        assert db.delete_by_metadata({"flag": False}) is False
        assert session.deleted == []
