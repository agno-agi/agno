"""Pinecone per-user isolation. The owner lives in ``metadata.user_id``; an absent key is shared.

Pinecone is cloud-only, so the index is mocked and the tests assert on the filter sent to it.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.pineconedb import PineconeDb

TEST_INDEX_NAME = f"isolation_test_{uuid.uuid4().hex[:8]}"
TEST_DIMENSION = 1024
USER_ID_KEY = "user_id"


@pytest.fixture
def mock_pinecone_index():
    """Create a mock Pinecone index."""
    index = MagicMock()
    empty_response = MagicMock()
    empty_response.matches = []
    index.query.return_value = empty_response
    return index


@pytest.fixture
def pinecone_db(mock_pinecone_index, mock_embedder):
    """Create a PineconeDb instance with mocked client and index."""
    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone", return_value=MagicMock()):
        db = PineconeDb(
            name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            spec={"serverless": {"cloud": "aws", "region": "us-west-2"}},
            embedder=mock_embedder,
            api_key="fake-api-key",
        )
        db._client = MagicMock()
        db._index = mock_pinecone_index
        yield db


def _doc(content="hello world", **kwargs):
    return Document(content=content, meta_data={"topic": "t"}, name="d", **kwargs)


class TestWriteStampsOwner:
    """Write stamps the owner into ``metadata.user_id``; ``None`` leaves the key absent."""

    def test_explicit_user_id_stamped_into_metadata(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="alice")

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert len(vectors) == 1
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"

    def test_none_user_id_is_shared(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id=None)

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert USER_ID_KEY not in vectors[0]["metadata"]

    def test_caller_metadata_cannot_spoof_owner(self, pinecone_db):
        """A caller's own ``user_id`` key in meta_data must not override the owner."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        doc = Document(content="c", meta_data={"user_id": "attacker"}, name="d")

        pinecone_db.upsert(content_hash="h1", documents=[doc], user_id="alice")

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"


class TestSearchScope:
    """A scoped search filters to the caller's own chunks or the shared bucket."""

    def test_scoped_search_builds_own_or_shared_filter(self, pinecone_db):
        pinecone_db.search(query="q", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$or": [
                {USER_ID_KEY: "alice"},
                {USER_ID_KEY: {"$exists": False}},
            ]
        }

    def test_scoped_search_ands_scope_onto_caller_filter(self, pinecone_db):
        caller_filter = {"topic": {"$eq": "t"}}
        pinecone_db.search(query="q", filters=caller_filter, user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$and": [
                caller_filter,
                {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]},
            ]
        }

    def test_admin_search_has_no_scope(self, pinecone_db):
        """``user_id=None`` applies no scope predicate."""
        pinecone_db.search(query="q", user_id=None)
        assert pinecone_db.index.query.call_args.kwargs["filter"] is None

        pinecone_db.index.query.reset_mock()
        pinecone_db.search(query="q", filters={"topic": {"$eq": "t"}}, user_id=None)
        assert pinecone_db.index.query.call_args.kwargs["filter"] == {"topic": {"$eq": "t"}}

    @pytest.mark.asyncio
    async def test_async_search_scopes_too(self, pinecone_db):
        await pinecone_db.async_search(query="q", user_id="alice")
        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]}


class TestDeleteScope:
    """``delete_by_content_id`` scopes the delete to the caller's own chunks."""

    def test_scoped_delete_matches_owner_only(self, pinecone_db):
        pinecone_db.delete_by_content_id("cid-1", user_id="alice")

        # Serverless deletes resolve the scope filter to ids via a query, so the scope is asserted there.
        # It matches the owner exactly — the shared bucket is not OR-ed into a delete.
        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_id": {"$eq": "cid-1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_unscoped_delete_is_content_id_only(self, pinecone_db):
        pinecone_db.delete_by_content_id("cid-1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_id": {"$eq": "cid-1"}}


class TestDedupScope:
    """The per-user dedup path keys on ``content_hash`` scoped by owner."""

    def test_content_hash_exists_scoped_to_owner(self, pinecone_db):
        pinecone_db.content_hash_exists("h1", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_content_hash_exists_none_is_shared_bucket_only(self, pinecone_db):
        pinecone_db.content_hash_exists("h1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}

    def test_delete_by_content_hash_scoped_to_owner(self, pinecone_db):
        pinecone_db._delete_by_content_hash("h1", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_delete_by_content_hash_none_deletes_shared_bucket_only(self, pinecone_db):
        """``None`` deletes the owner-absent shared bucket only, not every owner's chunks."""
        pinecone_db._delete_by_content_hash("h1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}


class TestOwnerFoldedId:
    """Two owners uploading identical content must both survive."""

    def test_owner_folded_id_is_distinct_per_owner(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="alice")
        alice_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        pinecone_db.index.upsert.reset_mock()
        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="bob")
        bob_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        assert alice_id != bob_id

    def test_shared_upload_keeps_document_id_verbatim(self, pinecone_db):
        """A shared upload is not folded — the plain document id is kept."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id=None)
        assert pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"] == "doc-1"

    def test_upsert_dedup_check_is_scoped_to_writing_owner(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")
        pinecone_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")

    def test_upsert_dedup_delete_is_scoped_to_writing_owner(self, pinecone_db):
        """The pre-delete on an existing hash is scoped to the writing owner."""
        pinecone_db.content_hash_exists = MagicMock(return_value=True)

        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "bob"}}


class TestFilteredReadsPaginate:
    """Pinecone caps ``top_k`` at 10 000 and returns no cursor.

    A single query silently truncates, so a delete resolved from a filter leaves the surplus
    chunks in place — still searchable after the re-upsert that was meant to replace them.
    """

    def _page(self, ids):
        response = MagicMock()
        response.matches = [MagicMock(id=i) for i in ids]
        return response

    def test_collect_ids_walks_past_the_top_k_cap(self, pinecone_db):
        first = [f"v{i}" for i in range(10000)]
        second = [f"v{i}" for i in range(10000, 10500)]
        pinecone_db.index.query.side_effect = [self._page(first), self._page(second)]

        ids = pinecone_db._collect_ids_by_filter({"content_hash": {"$eq": "h1"}})

        assert len(ids) == 10500
        # The second page must exclude what the first already returned, or it repeats forever
        assert set(pinecone_db.index.query.call_args_list[1].kwargs["filter"]["id"]["$nin"]) == set(first)

    def test_a_single_short_page_issues_one_query(self, pinecone_db):
        pinecone_db.index.query.side_effect = [self._page(["v1", "v2"])]

        ids = pinecone_db._collect_ids_by_filter({"content_hash": {"$eq": "h1"}})

        assert ids == ["v1", "v2"]
        assert pinecone_db.index.query.call_count == 1

    def test_a_repeating_page_terminates(self, pinecone_db):
        """A backend that ignores the exclusion must not spin the loop forever."""
        page = self._page([f"v{i}" for i in range(10000)])
        pinecone_db.index.query.side_effect = [page, page]

        ids = pinecone_db._collect_ids_by_filter({"content_hash": {"$eq": "h1"}})

        assert len(ids) == 10000
