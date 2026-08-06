"""OpenSearch per-user RAG isolation contract.

OpenSearch stores the owner in a top-level ``user_id`` keyword field. Chunks
written without an owner have no field at all, which is the state every
document written before this feature existed is already in.

* Inserts with ``user_id`` stamp the field and fold the owner into the _id, so
  two users ingesting the same bytes get two documents instead of overwriting
  each other.
* Inserts with ``user_id=None`` leave the field off - the SHARED bucket - and
  keep the pre-isolation _id.
* Scoped reads match ``term user_id`` OR ``must_not exists user_id``, so
  admin-uploaded content stays discoverable by every caller.
* Scoped deletes match ``term user_id`` alone - a caller can view shared content
  but cannot delete it, so clearing the shared bucket takes an unscoped call.
* Unscoped (admin) reads apply no scope and see everything.
* An empty or whitespace-only owner is refused: the shared bucket is the field
  being absent, so "" is a third bucket that no other caller can read, no scoped
  delete can reach, and ``content_hash_exists(user_id=None)`` cannot see.

The query bodies asserted here are the ones a real OpenSearch 2.19 cluster was
driven with, so they are the contract rather than a call-shape echo. Bucket
semantics are exercised through ``FakeIndex``, which evaluates the handful of
clause types the scope filter emits (term, exists, bool.should/must_not/filter)
the way the server does.
"""

from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.vectordb.opensearch import OpenSearch
from agno.vectordb.opensearch.index import Engine
from agno.vectordb.opensearch.opensearch import USER_ID_FIELD
from agno.vectordb.search import SearchType

TEST_INDEX_NAME = "isolation_test"
TEST_DIMENSION = 8

ALICE = "Alice's salary is $180,000."
BOB = "Bob's salary is $215,000."
SHARED = "The office is closed on January 1."


class FakeIndex:
    """An OpenSearch stand-in that really evaluates the clauses the scope filter emits.

    Only the clause types this backend builds are supported; anything else is a
    match-everything, which keeps the scoring clauses (knn, multi_match) out of
    the way so a test failure can only mean the scope is wrong.
    """

    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.indices = Mock()
        self.indices.exists.return_value = True
        self.indices.create.return_value = {"acknowledged": True}
        self.indices.put_mapping.return_value = {"acknowledged": True}
        self.mapping_updates: List[Dict[str, Any]] = []
        self.indices.put_mapping.side_effect = lambda index, body: self.mapping_updates.append(body)
        self.search_bodies: List[Dict[str, Any]] = []

    def value(self, source: Dict[str, Any], field: str) -> Any:
        """Resolve a dotted field path the way OpenSearch resolves meta_data.team.keyword."""
        node: Any = source
        for part in field.replace(".keyword", "").split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    def matches(self, source: Dict[str, Any], clause: Dict[str, Any]) -> bool:
        if "term" in clause:
            field, value = next(iter(clause["term"].items()))
            return self.value(source, field) == value
        if "exists" in clause:
            return self.value(source, clause["exists"]["field"]) is not None
        if "bool" in clause:
            body = clause["bool"]
            if not all(self.matches(source, c) for c in body.get("filter", [])):
                return False
            if not all(self.matches(source, c) for c in body.get("must", []) if "knn" not in c):
                return False
            must_not = body.get("must_not")
            if must_not is not None:
                clauses = must_not if isinstance(must_not, list) else [must_not]
                if any(self.matches(source, c) for c in clauses):
                    return False
            should = body.get("should")
            if should and body.get("minimum_should_match"):
                return any(self.matches(source, c) for c in should)
            return True
        # knn / multi_match / match_all contribute score, not selection.
        return True

    def _selected(self, query: Dict[str, Any]) -> List[str]:
        clause = query
        # A scoped knn query carries its filter inside the knn clause.
        if "knn" in clause:
            options = next(iter(clause["knn"].values()))
            clause = options.get("filter", {"match_all": {}})
        return [doc_id for doc_id, source in self.docs.items() if self.matches(source, clause)]

    def bulk(self, body, refresh=False):
        for action, payload in zip(body[::2], body[1::2]):
            if "index" in action:
                self.docs[action["index"]["_id"]] = payload
            elif "update" in action:
                self.docs.setdefault(action["update"]["_id"], {}).update(payload["doc"])
        return {"errors": False, "items": []}

    def search(self, index, body):
        self.search_bodies.append(body)
        hits = [
            {"_id": doc_id, "_score": 1.0, "_source": self.docs[doc_id]}
            for doc_id in self._selected(body["query"])[: body.get("size", 10)]
        ]
        return {"hits": {"hits": hits, "total": {"value": len(hits)}}}

    def delete_by_query(self, index, body, refresh=False, conflicts=None):
        doomed = self._selected(body["query"])
        for doc_id in doomed:
            del self.docs[doc_id]
        return {"deleted": len(doomed)}

    def count(self, index):
        return {"count": len(self.docs)}


class AsyncFakeIndex:
    """Async facade over the same FakeIndex, so the async half hits the same documents."""

    def __init__(self, index: FakeIndex):
        self._index = index
        self.indices = _AsyncFakeIndices(index)

    async def bulk(self, body, refresh=False):
        return self._index.bulk(body, refresh)

    async def search(self, index, body):
        return self._index.search(index, body)


class _AsyncFakeIndices:
    def __init__(self, index: FakeIndex):
        self._index = index

    async def exists(self, index):
        return self._index.indices.exists(index=index)

    async def create(self, index, body):
        return self._index.indices.create(index=index, body=body)

    async def put_mapping(self, index, body):
        return self._index.indices.put_mapping(index=index, body=body)


@pytest.fixture
def mock_embedder():
    embedder = Mock(spec=Embedder)
    embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    embedder.enable_batch = False
    return embedder


@pytest.fixture
def opensearch_db(mock_embedder):
    """An OpenSearch wired to FakeIndex, so reads and deletes really run the scope clause."""
    with (
        patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
        patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
    ):
        db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)
    db._client = FakeIndex()
    db._async_client = AsyncFakeIndex(db._client)
    return db


def doc(name: str, content: str, content_id: str = "cid") -> Document:
    return Document(id=name, name=name, content=content, content_id=content_id, embedding=[0.1] * TEST_DIMENSION)


def seed(db: OpenSearch) -> None:
    db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")
    db.insert("h_bob", [doc("bob", BOB)], user_id="bob")
    db.insert("h_shared", [doc("shared", SHARED)])


def texts(documents: List[Document]) -> List[str]:
    return sorted(d.content for d in documents)


class TestOwnerIsWritten:
    """The owner is a top-level keyword field, not a meta_data entry."""

    def test_user_id_key_constant(self):
        # Storage compatibility marker: renaming this makes every persisted
        # owner unreadable by the scope filter.
        assert USER_ID_FIELD == "user_id"

    def test_mapping_declares_user_id_as_keyword(self, opensearch_db):
        # keyword, not text: a text field would match the analyzed tokens of the
        # id instead of the id, so "Alice Smith" would match "alice".
        assert opensearch_db.mapping["mappings"]["properties"]["user_id"] == {"type": "keyword"}

    def test_scoped_insert_stamps_the_field(self, opensearch_db):
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")

        (source,) = opensearch_db.client.docs.values()
        assert source["user_id"] == "alice"
        assert "user_id" not in source["meta_data"]

    def test_unscoped_insert_leaves_the_field_absent(self, opensearch_db):
        opensearch_db.insert("h_shared", [doc("shared", SHARED)])

        (source,) = opensearch_db.client.docs.values()
        assert "user_id" not in source

    def test_two_owners_of_the_same_bytes_do_not_collide(self, opensearch_db):
        same = doc("template", "Quarterly review template.")

        opensearch_db.insert("h_same", [same], user_id="alice")
        opensearch_db.insert("h_same", [doc("template", "Quarterly review template.")], user_id="bob")

        assert len(opensearch_db.client.docs) == 2
        assert sorted(s["user_id"] for s in opensearch_db.client.docs.values()) == ["alice", "bob"]

    def test_two_owners_upserting_the_same_bytes_do_not_collide(self, opensearch_db):
        # upsert builds its own _id, so an owner-blind id here would make bob's
        # doc_as_upsert land on alice's document and rewrite its owner field.
        opensearch_db.upsert("h_same", [doc("template", "Quarterly review template.")], user_id="alice")
        opensearch_db.upsert("h_same", [doc("template", "Quarterly review template.")], user_id="bob")

        assert len(opensearch_db.client.docs) == 2
        assert sorted(s["user_id"] for s in opensearch_db.client.docs.values()) == ["alice", "bob"]

    def test_underscored_document_id_cannot_collide_with_a_different_split(self, opensearch_db):
        """The base id is collapsed with the content_hash into a fixed-length digest
        before the owner is folded in. Without that collapse the '_' boundary moves
        and ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') resolve to one _id,
        letting one owner overwrite the other's document."""
        left = doc("doc", "Any content")
        left.meta_data["content_hash"] = "1"
        right = doc("doc", "Any content")
        right.meta_data["content_hash"] = "1_a"

        assert opensearch_db._build_doc_id(left, "a_lice") != opensearch_db._build_doc_id(right, "lice")

        # whatever the caller passes, the owner is always folded into a fixed-length digest
        long_id = doc("doc_1_2_3", "Any content")
        long_id.meta_data["content_hash"] = "h"
        assert len(opensearch_db._build_doc_id(long_id, None)) == 32

    def test_unscoped_doc_id_is_unchanged(self, opensearch_db):
        """Existing indexes keep updating in place, so the fix is not a migration."""
        from hashlib import md5

        target = doc("legacy", "Legacy content")
        target.meta_data["content_hash"] = "h1"

        legacy_id = md5(b"legacy_h1").hexdigest()
        assert opensearch_db._build_doc_id(target, None) == legacy_id
        assert opensearch_db._build_doc_id(target, "alice") != legacy_id


class TestOwnerValidation:
    """An empty or whitespace-only owner is refused at every entry point that takes one.

    The shared bucket is the absence of the field, so "" is a third bucket rather
    than the shared one: a real 3.8.0 cluster indexes it as a keyword term, which
    ``must_not exists`` steps over and no named owner's ``term`` clause matches. Its
    chunks are then invisible to every other caller, invisible to
    ``content_hash_exists(user_id=None)``, and untouched by every scoped delete.
    """

    @pytest.mark.parametrize("bad", ["", "   \t  "])
    def test_rejects_unsafe_user_id(self, opensearch_db, bad):
        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            opensearch_db._validate_user_id(bad)
        # And the rejection is enforced on the write path, not just the helper.
        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id=bad)
        assert opensearch_db.client.docs == {}, "the guard must fire before anything is written"

    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.upsert("h_alice", [doc("alice", ALICE)], user_id=""),
            lambda db: db.search("salary", limit=10, user_id=""),
            lambda db: db.vector_search("salary", 10, None, ""),
            lambda db: db.keyword_search("salary", 10, None, ""),
            lambda db: db.hybrid_search("salary", 10, None, ""),
            lambda db: db.content_hash_exists("h_alice", user_id=""),
            lambda db: db.delete_by_content_id("cid", user_id=""),
        ],
        ids=["upsert", "search", "vector", "keyword", "hybrid", "content_hash_exists", "delete_by_content_id"],
    )
    def test_every_scoped_entry_point_rejects(self, opensearch_db, call):
        seed(opensearch_db)

        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            call(opensearch_db)

        assert len(opensearch_db.client.docs) == 3, "the guard must fire before anything is written or deleted"

    def test_search_rejects_before_the_search_type_dispatch(self, opensearch_db):
        """An unrecognised search type returns [] without reaching any leaf, so the
        dispatcher has to check the owner itself rather than lean on the leaf it picks."""
        opensearch_db.search_type = "not_a_search_type"

        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            opensearch_db.search("salary", limit=10, user_id="")

    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.async_insert("h_alice", [doc("alice", ALICE)], user_id=""),
            lambda db: db.async_upsert("h_alice", [doc("alice", ALICE)], user_id=""),
            lambda db: db.async_search("salary", limit=10, user_id=""),
        ],
        ids=["async_insert", "async_upsert", "async_search"],
    )
    async def test_every_async_entry_point_rejects(self, opensearch_db, call):
        """async_search delegates to search on a worker thread, so the ValueError has
        to survive the thread hop and the await."""
        seed(opensearch_db)

        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            await call(opensearch_db)

    def test_none_is_not_rejected_anywhere(self, opensearch_db):
        """None is the shared bucket on a write and the admin view on a read - it is
        the one value the guard must let through, not the one it exists to catch."""
        opensearch_db.insert("h_shared", [doc("shared", SHARED)], user_id=None)
        opensearch_db.upsert("h_shared", [doc("shared", SHARED)], user_id=None)

        assert opensearch_db.search("office", limit=10, user_id=None) != []
        assert opensearch_db.vector_search("office", 10, None, None) != []
        assert opensearch_db.keyword_search("office", 10, None, None) != []
        assert opensearch_db.hybrid_search("office", 10, None, None) != []
        assert opensearch_db.content_hash_exists("h_shared", user_id=None) is True
        assert opensearch_db.delete_by_content_id("cid", user_id=None) is True

    @pytest.mark.asyncio
    async def test_none_is_not_rejected_on_the_async_half(self, opensearch_db):
        await opensearch_db.async_insert("h_shared", [doc("shared", SHARED)], user_id=None)
        await opensearch_db.async_upsert("h_shared", [doc("shared", SHARED)], user_id=None)

        assert await opensearch_db.async_search("office", limit=10, user_id=None) != []

    @pytest.mark.parametrize("owner", ["a*", "?", "{alice}", "a|b", "a\x1fb", "alice ", "ALICE", "a b"])
    def test_owners_that_only_a_tag_index_would_have_to_refuse_are_kept(self, opensearch_db, owner):
        """The guard stops at ""/whitespace on purpose.

        The sibling TAG-indexed backends also refuse wildcards, braces, unions, a
        record separator and reserved sentinels, because their owner is one token in
        a packed tag list read back through a query parser. Here the owner is its own
        keyword field matched by a term clause, there is no sentinel - the shared
        bucket is the field being absent - and the owner never reaches Lucene's query
        syntax, so a 3.8.0 cluster round-trips every one of these as an ordinary
        exact-match owner. Refusing them would be an invented restriction.
        """
        opensearch_db.insert("h_x", [doc("x", "Only this owner's chunk.")], user_id=owner)

        (source,) = opensearch_db.client.docs.values()
        assert source["user_id"] == owner
        assert texts(opensearch_db.search("chunk", limit=10, user_id=owner)) == ["Only this owner's chunk."]
        assert opensearch_db.search("chunk", limit=10, user_id="alice") == []


class TestScopedReads:
    """search(user_id=X) returns X's chunks plus the shared bucket, never another owner's."""

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_owner_sees_own_and_shared(self, opensearch_db, search_type):
        opensearch_db.search_type = search_type
        seed(opensearch_db)

        assert texts(opensearch_db.search("salary", limit=10, user_id="alice")) == sorted([ALICE, SHARED])

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_owner_never_sees_another_owner(self, opensearch_db, search_type):
        opensearch_db.search_type = search_type
        seed(opensearch_db)

        assert BOB not in texts(opensearch_db.search("salary", limit=10, user_id="alice"))
        assert ALICE not in texts(opensearch_db.search("salary", limit=10, user_id="bob"))

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_unscoped_search_sees_everything(self, opensearch_db, search_type):
        opensearch_db.search_type = search_type
        seed(opensearch_db)

        assert texts(opensearch_db.search("salary", limit=10, user_id=None)) == sorted([ALICE, BOB, SHARED])

    def test_unknown_owner_sees_only_the_shared_bucket(self, opensearch_db):
        seed(opensearch_db)

        assert texts(opensearch_db.search("salary", limit=10, user_id="carol")) == [SHARED]

    def test_direct_search_methods_are_scoped(self, opensearch_db):
        seed(opensearch_db)

        for method in (opensearch_db.vector_search, opensearch_db.keyword_search, opensearch_db.hybrid_search):
            assert texts(method("salary", 10, None, "alice")) == sorted([ALICE, SHARED])

    def test_scope_composes_with_metadata_filters(self, opensearch_db):
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], {"team": "eng"}, user_id="alice")
        opensearch_db.insert("h_alice2", [doc("alice2", "Alice's laptop is a Mac.")], {"team": "ops"}, user_id="alice")
        opensearch_db.insert("h_bob", [doc("bob", BOB)], {"team": "eng"}, user_id="bob")

        found = opensearch_db.search("salary", limit=10, filters={"team": "eng"}, user_id="alice")

        assert texts(found) == [ALICE]


class TestScopedReadsAsync:
    """async_search must be symmetric with search - it delegates to it on a worker thread."""

    @pytest.mark.asyncio
    async def test_async_owner_sees_own_and_shared(self, opensearch_db):
        seed(opensearch_db)

        assert texts(await opensearch_db.async_search("salary", limit=10, user_id="alice")) == sorted([ALICE, SHARED])

    @pytest.mark.asyncio
    async def test_async_owner_never_sees_another_owner(self, opensearch_db):
        seed(opensearch_db)

        assert BOB not in texts(await opensearch_db.async_search("salary", limit=10, user_id="alice"))

    @pytest.mark.asyncio
    async def test_async_unscoped_sees_everything(self, opensearch_db):
        seed(opensearch_db)

        found = await opensearch_db.async_search("salary", limit=10, user_id=None)
        assert texts(found) == sorted([ALICE, BOB, SHARED])

    @pytest.mark.asyncio
    async def test_async_insert_and_upsert_stamp_the_owner(self, opensearch_db):
        await opensearch_db.async_insert("h_alice", [doc("alice", ALICE)], user_id="alice")
        await opensearch_db.async_upsert("h_bob", [doc("bob", BOB)], user_id="bob")

        assert sorted(s["user_id"] for s in opensearch_db.client.docs.values()) == ["alice", "bob"]


class TestQueryShape:
    """The clauses sent to OpenSearch. These bodies were driven against a real 2.19 cluster."""

    SCOPE = {
        "bool": {
            "should": [
                {"term": {"user_id": "alice"}},
                {"bool": {"must_not": {"exists": {"field": "user_id"}}}},
            ],
            "minimum_should_match": 1,
        }
    }

    OWNER = {"term": {"user_id": "alice"}}

    SHARED_BUCKET = {"bool": {"must_not": {"exists": {"field": "user_id"}}}}

    def test_scope_clause(self, opensearch_db):
        assert opensearch_db._user_scope_filter("alice") == self.SCOPE

    def test_no_scope_clause_when_unscoped(self, opensearch_db):
        assert opensearch_db._user_scope_filter(None) is None

    def test_owner_clause_has_no_shared_arm(self, opensearch_db):
        """The delete scope is the owner term on its own - no must_not exists arm."""
        assert opensearch_db._owner_filter("alice") == self.OWNER

    def test_shared_bucket_clause_is_the_absence_of_the_field(self, opensearch_db):
        """The shared bucket is not a sentinel value, so it also covers every
        document written before this field existed."""
        assert opensearch_db._shared_bucket_filter() == self.SHARED_BUCKET

    def test_vector_query_pre_filters_inside_the_knn_clause(self, opensearch_db):
        """Post-filtering the k nearest neighbours returns nothing when they all
        belong to another owner, so a scoped knn query has to filter first."""
        body = opensearch_db._build_vector_query("q", 5, None, "alice")

        assert body["query"]["knn"]["embedding"]["filter"] == {"bool": {"filter": [self.SCOPE]}}
        assert "bool" not in body["query"]

    def test_vector_query_unscoped_shape_is_unchanged(self, opensearch_db):
        """Callers who never pass user_id must get the exact query they got before."""
        assert opensearch_db._build_vector_query("q", 5, None, None) == {
            "size": 5,
            "query": {"knn": {"embedding": {"vector": [0.1] * TEST_DIMENSION, "k": 5}}},
        }

    def test_nmslib_falls_back_to_post_filtering(self, mock_embedder):
        """NMSLIB answers a filtered knn query with "does not support filters"."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                engine=Engine.nmslib,
            )

        assert db.supports_knn_filter is False
        body = db._build_vector_query("q", 5, None, "alice")
        assert "filter" not in body["query"]["bool"]["must"][0]["knn"]["embedding"]
        assert body["query"]["bool"]["filter"] == [self.SCOPE]

    def test_keyword_query_carries_the_scope(self, opensearch_db):
        body = opensearch_db._build_keyword_query("q", 5, None, "alice")

        assert body["query"]["bool"]["filter"] == [self.SCOPE]

    def test_hybrid_query_scopes_both_halves(self, opensearch_db):
        body = opensearch_db._build_hybrid_query("q", 5, None, "alice")

        # The bool filter scopes the multi_match half and the result set as a whole.
        assert body["query"]["bool"]["filter"] == [self.SCOPE]
        # The knn half repeats it so its k neighbours come from the scoped set.
        knn = body["query"]["bool"]["should"][0]["knn"]["embedding"]
        assert knn["filter"] == {"bool": {"filter": [self.SCOPE]}}


class TestScopedDelete:
    def test_owner_delete_leaves_other_owners_alone(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.delete_by_content_id("cid", user_id="alice") is True

        assert texts(opensearch_db.search("salary", limit=10, user_id=None)) == sorted([BOB, SHARED])

    def test_owner_delete_leaves_the_shared_bucket_alone(self, opensearch_db):
        """A caller can view shared content but cannot delete it, so the shared
        chunks survive a scoped delete and stay retrievable."""
        opensearch_db.insert("h_shared", [doc("shared", SHARED)])

        opensearch_db.delete_by_content_id("cid", user_id="alice")

        assert texts(opensearch_db.search("office", limit=10, user_id="alice")) == [SHARED]

    def test_unscoped_delete_removes_the_shared_bucket(self, opensearch_db):
        """Removing shared content is the admin path."""
        opensearch_db.insert("h_shared", [doc("shared", SHARED)])

        opensearch_db.delete_by_content_id("cid")

        assert opensearch_db.client.docs == {}

    def test_unscoped_delete_removes_every_owner(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.delete_by_content_id("cid") is True

        assert opensearch_db.client.docs == {}


class TestContentHashExistsScope:
    """The dedup existence gate ``Knowledge`` consults for ``skip_if_exists``.
    Scoped it reads the caller's chunks plus the shared bucket, so an upload
    another owner made is not judged a duplicate. ``None`` reads the shared
    bucket alone - the field being absent - rather than every owner."""

    def test_owner_sees_his_own_hash(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.content_hash_exists("h_alice", user_id="alice") is True

    def test_another_owners_hash_is_not_a_duplicate(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.content_hash_exists("h_bob", user_id="alice") is False

    def test_a_privately_owned_hash_is_not_in_the_shared_bucket(self, opensearch_db):
        """The regression. ``None`` applied no scope at all, so a hash alice
        privately held read as a duplicate for the shared bucket - and a later
        shared publish under ``skip_if_exists`` was swallowed, leaving the shared
        bucket without the content it was asked to hold."""
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")

        assert opensearch_db.content_hash_exists("h_alice", user_id=None) is False

    def test_unscoped_check_sees_the_shared_bucket(self, opensearch_db):
        opensearch_db.insert("h_shared", [doc("shared", SHARED)])

        assert opensearch_db.content_hash_exists("h_shared", user_id=None) is True

    def test_unscoped_check_sends_the_shared_bucket_clause(self, opensearch_db):
        seed(opensearch_db)

        opensearch_db.content_hash_exists("h_alice", user_id=None)

        assert opensearch_db.client.search_bodies[-1]["query"] == {
            "bool": {"filter": [{"term": {"content_hash": "h_alice"}}, TestQueryShape.SHARED_BUCKET]}
        }

    def test_shared_publish_survives_a_private_holder(self, opensearch_db):
        """The user-visible half: the shared publish is not skipped, so alice's
        chunk and the shared one both exist and bob can retrieve the shared one."""
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")

        if not opensearch_db.content_hash_exists("h_alice", user_id=None):
            opensearch_db.insert("h_alice", [doc("shared", ALICE)])

        assert texts(opensearch_db.search("salary", limit=10, user_id="bob")) == [ALICE]


class TestLegacyIndexCompatibility:
    """An index created before this field existed has to keep working."""

    def test_documents_without_the_field_read_as_shared(self, opensearch_db):
        opensearch_db.client.docs["old"] = {"content": "Legacy handbook.", "meta_data": {}}

        found = opensearch_db.search("handbook", limit=10, user_id="alice")

        assert texts(found) == ["Legacy handbook."]

    def test_documents_without_the_field_are_not_deletable_by_an_owner(self, opensearch_db):
        """Every document written before this field existed reads as shared, so an
        owner-scoped delete must not be able to reach any of them."""
        opensearch_db.client.docs["old"] = {"content": "Legacy handbook.", "meta_data": {}, "content_id": "cid"}

        opensearch_db.delete_by_content_id("cid", user_id="alice")

        assert list(opensearch_db.client.docs) == ["old"]

    def test_the_index_mapping_is_never_written_to(self, opensearch_db):
        """Schema changes ship as an explicit migration, so nothing here alters a
        mapping the user already has. An index predating this field keeps its own
        shape until the operator migrates it."""
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")
        opensearch_db.insert("h_bob", [doc("bob", BOB)], user_id="bob")

        assert opensearch_db.client.mapping_updates == []
