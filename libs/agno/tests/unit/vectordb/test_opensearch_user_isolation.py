"""OpenSearch per-user RAG isolation. The owner is a top-level ``user_id`` field; its absence is the shared bucket."""

from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.opensearch import OpenSearch
from agno.vectordb.opensearch.index import Engine
from agno.vectordb.search import SearchType

from .conftest import DeterministicEmbedder

TEST_INDEX_NAME = "isolation_test"
TEST_DIMENSION = 8

ALICE = "Alice's salary is $180,000."
BOB = "Bob's salary is $215,000."
SHARED = "The office is closed on January 1."


class FakeIndex:
    """An OpenSearch stand-in that evaluates the clauses the scope filter emits."""

    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.indices = Mock()
        self.indices.exists.return_value = True
        self.indices.create.return_value = {"acknowledged": True}
        self.indices.put_mapping.return_value = {"acknowledged": True}
        self.mapping_updates: List[Dict[str, Any]] = []
        # A legacy index: the owner field is absent until something declares it, and
        # get_mapping has to report that faithfully or the adapter cannot tell.
        self.mapped_properties: Dict[str, Any] = {}
        self.indices.put_mapping.side_effect = self._put_mapping
        self.indices.get_mapping.side_effect = self._get_mapping
        self.search_bodies: List[Dict[str, Any]] = []

    def _put_mapping(self, index, body):
        self.mapping_updates.append(body)
        self.mapped_properties.update(body.get("properties", {}))
        return {"acknowledged": True}

    def _get_mapping(self, index):
        return {index: {"mappings": {"properties": dict(self.mapped_properties)}}}

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
def opensearch_db():
    """OpenSearch instance wired to FakeIndex, so reads and deletes run the real scope clause."""
    with (
        patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
        patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
    ):
        db = OpenSearch(
            index_name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            embedder=DeterministicEmbedder(dimensions=TEST_DIMENSION),
        )
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


class TestWriteStampsOwner:
    """The owner is a top-level keyword field, not a meta_data entry."""

    def test_mapping_declares_user_id_as_keyword(self, opensearch_db):
        # keyword, not text: a text field would match the analyzed tokens of the id, so "Alice Smith" matches "alice".
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
        # upsert builds its own _id: an owner-blind one would land bob's doc_as_upsert on alice's document.
        opensearch_db.upsert("h_same", [doc("template", "Quarterly review template.")], user_id="alice")
        opensearch_db.upsert("h_same", [doc("template", "Quarterly review template.")], user_id="bob")

        assert len(opensearch_db.client.docs) == 2
        assert sorted(s["user_id"] for s in opensearch_db.client.docs.values()) == ["alice", "bob"]

    def test_underscored_id_does_not_collide(self, opensearch_db):
        """The base id and the content_hash are digested before the owner is folded in."""
        left = doc("doc", "Any content")
        left.meta_data["content_hash"] = "1"
        right = doc("doc", "Any content")
        right.meta_data["content_hash"] = "1_a"

        assert opensearch_db._build_doc_id(left, "a_lice") != opensearch_db._build_doc_id(right, "lice")

        long_id = doc("doc_1_2_3", "Any content")
        long_id.meta_data["content_hash"] = "h"
        assert len(opensearch_db._build_doc_id(long_id, None)) == 32

    def test_unscoped_doc_id_is_unchanged(self, opensearch_db):
        """Unscoped ids are unchanged, so existing indexes keep updating in place."""
        from hashlib import md5

        target = doc("legacy", "Legacy content")
        target.meta_data["content_hash"] = "h1"

        legacy_id = md5(b"legacy_h1").hexdigest()
        assert opensearch_db._build_doc_id(target, None) == legacy_id
        assert opensearch_db._build_doc_id(target, "alice") != legacy_id


class TestOwnerValidation:
    """An empty or whitespace-only owner is refused at every entry point that takes one."""

    @pytest.mark.parametrize("bad", ["", "   \t  "])
    def test_rejects_unsafe_user_id(self, opensearch_db, bad):
        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            opensearch_db._validate_user_id(bad)
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
        """An unrecognised search type reaches no leaf, so the dispatcher has to check the owner itself."""
        opensearch_db.search_type = "not_a_search_type"

        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            opensearch_db.search("salary", limit=10, user_id="")

    @pytest.mark.asyncio
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
        """async_search delegates to search on a worker thread, so the ValueError has to survive the thread hop."""
        seed(opensearch_db)

        with pytest.raises(ValueError, match="user_id must not be empty or whitespace-only"):
            await call(opensearch_db)

    def test_none_is_not_rejected_anywhere(self, opensearch_db):
        """None is the shared bucket on a write and the admin view on a read, so the guard must let it through."""
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
    def test_exotic_owner_ids_are_accepted(self, opensearch_db, owner):
        """The guard stops at ""/whitespace on purpose."""
        opensearch_db.insert("h_x", [doc("x", "Only this owner's chunk.")], user_id=owner)

        (source,) = opensearch_db.client.docs.values()
        assert source["user_id"] == owner
        assert texts(opensearch_db.search("chunk", limit=10, user_id=owner)) == ["Only this owner's chunk."]
        assert opensearch_db.search("chunk", limit=10, user_id="alice") == []


class TestSearchScope:
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


class TestAsyncIsolation:
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


class TestSearchQueryShape:
    """The clauses sent to OpenSearch."""

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
        """Not a sentinel value, so it also covers documents written before the field existed."""
        assert opensearch_db._shared_bucket_filter() == self.SHARED_BUCKET

    def test_vector_query_pre_filters_inside_the_knn_clause(self, opensearch_db):
        """Post-filtering returns nothing when the k nearest neighbours all belong to another owner."""
        body = opensearch_db._build_vector_query("q", 5, None, "alice")

        assert body["query"]["knn"]["embedding"]["filter"] == {"bool": {"filter": [self.SCOPE]}}
        assert "bool" not in body["query"]

    def test_vector_query_unscoped_shape_is_unchanged(self, opensearch_db):
        """Callers who never pass user_id must get the exact query they got before."""
        vector = opensearch_db.embedder.get_embedding("q")
        assert opensearch_db._build_vector_query("q", 5, None, None) == {
            "size": 5,
            "query": {"knn": {"embedding": {"vector": vector, "k": 5}}},
        }

    def test_nmslib_falls_back_to_post_filtering(self):
        """NMSLIB answers a filtered knn query with "does not support filters"."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=DeterministicEmbedder(dimensions=TEST_DIMENSION),
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

        # The scope is repeated inside the knn half so its k neighbours come from the scoped set.
        assert body["query"]["bool"]["filter"] == [self.SCOPE]
        knn = body["query"]["bool"]["should"][0]["knn"]["embedding"]
        assert knn["filter"] == {"bool": {"filter": [self.SCOPE]}}


class TestDeleteScope:
    def test_owner_delete_leaves_other_owners_alone(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.delete_by_content_id("cid", user_id="alice") is True

        assert texts(opensearch_db.search("salary", limit=10, user_id=None)) == sorted([BOB, SHARED])

    def test_owner_delete_leaves_the_shared_bucket_alone(self, opensearch_db):
        """A caller can view shared content but cannot delete it."""
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
    """The dedup existence gate ``Knowledge`` consults for ``skip_if_exists``."""

    def test_owner_sees_his_own_hash(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.content_hash_exists("h_alice", user_id="alice") is True

    def test_another_owners_hash_is_not_a_duplicate(self, opensearch_db):
        seed(opensearch_db)

        assert opensearch_db.content_hash_exists("h_bob", user_id="alice") is False

    def test_a_privately_owned_hash_is_not_in_the_shared_bucket(self, opensearch_db):
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")

        assert opensearch_db.content_hash_exists("h_alice", user_id=None) is False

    def test_unscoped_check_sees_the_shared_bucket(self, opensearch_db):
        opensearch_db.insert("h_shared", [doc("shared", SHARED)])

        assert opensearch_db.content_hash_exists("h_shared", user_id=None) is True

    def test_unscoped_check_sends_the_shared_bucket_clause(self, opensearch_db):
        seed(opensearch_db)

        opensearch_db.content_hash_exists("h_alice", user_id=None)

        assert opensearch_db.client.search_bodies[-1]["query"] == {
            "bool": {"filter": [{"term": {"content_hash": "h_alice"}}, TestSearchQueryShape.SHARED_BUCKET]}
        }

    def test_shared_publish_survives_a_private_holder(self, opensearch_db):
        """A private holder of the hash must not make the shared publish look like a duplicate."""
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
        """Documents written before the field existed read as shared, so an owner-scoped delete cannot reach them."""
        opensearch_db.client.docs["old"] = {"content": "Legacy handbook.", "meta_data": {}, "content_id": "cid"}

        opensearch_db.delete_by_content_id("cid", user_id="alice")

        assert list(opensearch_db.client.docs) == ["old"]

    def test_only_the_owner_field_is_ever_added_to_the_mapping(self, opensearch_db):
        """An owned write declares ``user_id`` as a keyword and touches nothing else.

        Adding the field is the one mapping change the adapter makes, and it has to happen
        before the first stamped value: OpenSearch would otherwise dynamic-map that value as
        analyzed text, which no scope filter can honour and which an index can never undo.
        """
        opensearch_db.insert("h_alice", [doc("alice", ALICE)], user_id="alice")
        opensearch_db.insert("h_bob", [doc("bob", BOB)], user_id="bob")

        assert opensearch_db.client.mapping_updates == [{"properties": {"user_id": {"type": "keyword"}}}]

    def test_an_unowned_write_leaves_the_mapping_alone(self, opensearch_db):
        """The shared bucket is the absence of the field, so it needs no declaration."""
        opensearch_db.insert("h_shared", [doc("shared", SHARED)], user_id=None)

        assert opensearch_db.client.mapping_updates == []


def gated_db(mapping_response):
    """An adapter whose live mapping is whatever the test says it is."""
    db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=DeterministicEmbedder())
    db._client = Mock()
    db._client.indices.get_mapping.return_value = mapping_response
    return db


def mapping_for(index_name, user_id_type):
    """A get_mapping response; ``user_id_type=None`` leaves the field out entirely."""
    properties = {} if user_id_type is None else {"user_id": {"type": user_id_type}}
    return {index_name: {"mappings": {"properties": properties}}}


class TestOwnerFieldMappingGate:
    """A scope filter is only honoured when the live mapping stores the owner as an exact term.

    OpenSearch dynamic-maps a string as analyzed ``text``, so the first scoped write to an index
    created before the field existed types it wrongly, and ``{"term": {"user_id": x}}`` then matches
    that value's tokens: user_id="dave" also matches "Dave" and "dave smith".
    """

    def test_keyword_mapping_is_honoured(self):
        db = gated_db(mapping_for(TEST_INDEX_NAME, "keyword"))

        assert db._require_owner_field("alice") is True

    def test_analyzed_mapping_refuses_a_scoped_operation(self):
        db = gated_db(mapping_for(TEST_INDEX_NAME, "text"))

        with pytest.raises(ValueError, match="recreate the index"):
            db._require_owner_field("alice")

    def test_a_keyword_subfield_does_not_rescue_an_analyzed_parent(self):
        """The dynamic default is text with a .keyword subfield, but the filter names the parent."""
        db = gated_db(
            {
                TEST_INDEX_NAME: {
                    "mappings": {
                        "properties": {"user_id": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}}
                    }
                }
            }
        )

        with pytest.raises(ValueError, match="recreate the index"):
            db._require_owner_field("alice")

    def test_analyzed_mapping_still_serves_an_unscoped_operation(self):
        """Unscoped callers never name the field, so a wrong mapping cannot mismatch for them."""
        db = gated_db(mapping_for(TEST_INDEX_NAME, "text"))

        assert db._require_owner_field(None) is False

    def test_an_absent_field_is_the_shared_bucket_not_a_refusal(self):
        """The documented pre-v3 contract: no owners stored, so every document reads as shared."""
        db = gated_db(mapping_for(TEST_INDEX_NAME, None))

        assert db._require_owner_field("alice") is True

    def test_an_alias_is_judged_by_every_index_it_resolves_to(self):
        """get_mapping keys by concrete index, so the alias name is absent from its own response."""
        db = gated_db(
            {
                "concrete-good": {"mappings": {"properties": {"user_id": {"type": "keyword"}}}},
                "concrete-bad": {"mappings": {"properties": {"user_id": {"type": "text"}}}},
            }
        )

        with pytest.raises(ValueError, match="recreate the index"):
            db._require_owner_field("alice")

    def test_an_alias_resolving_only_to_exact_indexes_is_honoured(self):
        db = gated_db(
            {
                "concrete-a": {"mappings": {"properties": {"user_id": {"type": "keyword"}}}},
                "concrete-b": {"mappings": {"properties": {"user_id": {"type": "keyword"}}}},
            }
        )

        assert db._require_owner_field("alice") is True
        # An alias can be repointed while the process lives, so its verdict is never cached.
        assert db._owner_field_exact is None

    def test_an_unreadable_mapping_does_not_refuse_and_is_not_cached(self):
        """A blip must not permanently mask a real legacy index, so it is re-inspected next time."""
        db = gated_db(None)
        db._client.indices.get_mapping.side_effect = RuntimeError("cluster unreachable")

        assert db._require_owner_field("alice") is True
        assert db._owner_field_exact is None

    def test_an_exact_mapping_is_inspected_once(self):
        db = gated_db(mapping_for(TEST_INDEX_NAME, "keyword"))

        for _ in range(3):
            db._require_owner_field("alice")

        assert db._client.indices.get_mapping.call_count == 1

    def test_create_records_the_mapping_it_just_wrote(self):
        db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=DeterministicEmbedder())
        db._client = Mock()
        db._client.indices.exists.return_value = False

        db.create()

        assert db._require_owner_field("alice") is True
        assert db._client.indices.get_mapping.call_count == 0

    def test_drop_forgets_the_mapping_of_the_index_it_removed(self):
        db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=DeterministicEmbedder())
        db._client = Mock()
        db._client.indices.exists.return_value = True
        db._owner_field_exact = True

        db.drop()

        assert db._owner_field_exact is None

    @pytest.mark.parametrize(
        "operation",
        [
            lambda db: db.search("q", user_id="alice"),
            lambda db: db.vector_search("q", user_id="alice"),
            lambda db: db.keyword_search("q", user_id="alice"),
            lambda db: db.hybrid_search("q", user_id="alice"),
            lambda db: db.insert("h", [doc("alice", ALICE)], user_id="alice"),
            lambda db: db.upsert("h", [doc("alice", ALICE)], user_id="alice"),
            lambda db: db.content_hash_exists("h", user_id="alice"),
            lambda db: db.delete_by_content_id("cid", user_id="alice"),
        ],
    )
    def test_every_scoped_entry_point_is_gated(self, operation):
        db = gated_db(mapping_for(TEST_INDEX_NAME, "text"))

        with pytest.raises(ValueError, match="recreate the index"):
            operation(db)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "operation",
        [
            lambda db: db.async_search("q", user_id="alice"),
            lambda db: db.async_insert("h", [doc("alice", ALICE)], user_id="alice"),
            lambda db: db.async_upsert("h", [doc("alice", ALICE)], user_id="alice"),
        ],
    )
    async def test_every_scoped_async_entry_point_is_gated(self, operation):
        db = gated_db(mapping_for(TEST_INDEX_NAME, "text"))

        with pytest.raises(ValueError, match="recreate the index"):
            await operation(db)
