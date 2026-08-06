"""Qdrant per-user RAG isolation contract.

Qdrant's vendor-recommended multi-tenancy is a single collection with a
tenant-indexed payload field. We index ``user_id`` as a KEYWORD with
``is_tenant=True`` so the engine stores tenant data contiguously and can
prune by tenant before walking the HNSW graph.

* Inserts with ``user_id`` stamp the value into the payload's ``user_id``
  field (NOT inside ``meta_data``).
* Inserts with ``user_id=None`` leave it NULL — the SHARED bucket.
* Scoped searches send a Filter whose ``should`` matches either the caller's
  id OR is_empty(user_id), so admin-uploaded shared content stays
  discoverable.
* Unscoped (admin) searches send no filter and see everything.

Two engines drive this file, because neither one alone covers the contract.

``FakeQdrantClient`` keeps the Filter objects the backend constructed and
evaluates them against stored payloads, so the tests below can assert on query
SHAPE — the exact ``models.Filter``, the ``is_tenant`` index call, the way the
owner arm and ``IsEmptyCondition`` compose. Qdrant's local mode silently drops
the ``is_tenant`` payload index, so that assertion is only possible here.

``real_qdrant_db`` is a genuine in-memory Qdrant (``location=":memory:"``). It
proves the BEHAVIOUR end to end and, just as importantly, that the filters we
build are ones the engine actually accepts — a malformed ``models.Filter`` a
real server would reject sails straight through the fake.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from qdrant_client.http import models

from agno.knowledge.document import Document
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.qdrant.qdrant import USER_ID_PAYLOAD_KEY

TEST_COLLECTION = "isolation_test"


class FakeQdrantClient:
    """A Qdrant stand-in that evaluates the Filter the backend built.

    Only the condition types the scope filter emits are supported — nested
    ``Filter``, ``FieldCondition``/``MatchValue`` and ``IsEmptyCondition``.
    Anything else raises, so a filter that changes shape fails loudly instead
    of quietly matching every point.
    """

    def __init__(self):
        self.points: Dict[Any, models.PointStruct] = {}
        self.collections: List[str] = []
        # The filters the backend handed to the server, in call order.
        self.query_filters: List[Optional[models.Filter]] = []
        self.count_filters: List[Optional[models.Filter]] = []
        self.delete_filters: List[models.Filter] = []
        self.payload_indexes: List[Dict[str, Any]] = []

    def value(self, payload: Dict[str, Any], key: str) -> Any:
        """Resolve a dotted payload path the way Qdrant resolves meta_data.team."""
        node: Any = payload
        for part in key.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    def matches(self, payload: Dict[str, Any], condition: Any) -> bool:
        if isinstance(condition, models.Filter):
            must = condition.must or []
            if not all(self.matches(payload, c) for c in must):
                return False
            if condition.should and not any(self.matches(payload, c) for c in condition.should):
                return False
            if condition.must_not and any(self.matches(payload, c) for c in condition.must_not):
                return False
            return True
        if isinstance(condition, models.FieldCondition):
            match = condition.match
            if not isinstance(match, models.MatchValue):
                raise AssertionError(f"FakeQdrantClient cannot evaluate match {match!r}")
            return self.value(payload, condition.key) == match.value
        if isinstance(condition, models.IsEmptyCondition):
            value = self.value(payload, condition.is_empty.key)
            return value is None or value == []
        raise AssertionError(f"FakeQdrantClient cannot evaluate condition {condition!r}")

    def _selected(self, condition: Optional[models.Filter]) -> List[Any]:
        return [
            point_id
            for point_id, point in self.points.items()
            if condition is None or self.matches(point.payload or {}, condition)
        ]

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, vectors_config=None, sparse_vectors_config=None) -> None:
        self.collections.append(collection_name)

    def create_payload_index(self, collection_name: str, field_name: str, field_schema=None) -> None:
        self.payload_indexes.append({"field_name": field_name, "field_schema": field_schema})

    def delete_collection(self, collection_name: str) -> None:
        self.collections.remove(collection_name)

    def upsert(self, collection_name: str, points, wait=False) -> None:
        for point in points:
            self.points[point.id] = point

    def query_points(self, collection_name: str, query=None, query_filter=None, limit=10, **kwargs):
        self.query_filters.append(query_filter)
        selected = self._selected(query_filter)[:limit]
        return SimpleNamespace(points=[self.points[point_id] for point_id in selected])

    def scroll(self, collection_name: str, limit=10, with_payload=True):
        return [self.points[point_id] for point_id in list(self.points)[:limit]], None

    def count(self, collection_name: str, count_filter=None, exact=True):
        self.count_filters.append(count_filter)
        return SimpleNamespace(count=len(self._selected(count_filter)))

    def delete(self, collection_name: str, points_selector, wait=True):
        self.delete_filters.append(points_selector)
        for point_id in self._selected(points_selector):
            del self.points[point_id]
        return SimpleNamespace(status=models.UpdateStatus.COMPLETED)


@pytest.fixture
def qdrant_db(mock_embedder):
    """A Qdrant wired to FakeQdrantClient — no engine, in-memory or otherwise."""
    db = Qdrant(collection=TEST_COLLECTION, embedder=mock_embedder)
    db._client = FakeQdrantClient()  # type: ignore[assignment]
    db.create()
    return db


@pytest.fixture
def real_qdrant_db(mock_embedder):
    """A fresh real Qdrant per test, in-memory so no cleanup is required."""
    db = Qdrant(
        collection=TEST_COLLECTION,
        location=":memory:",
        embedder=mock_embedder,
    )
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


def _owners(db) -> List[Optional[str]]:
    """Owner of every stored point, the shared bucket's NULL included. Sorted
    by ``str`` so ``None`` can sit alongside real ids."""
    points, _ = db.client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
    return sorted((point.payload[USER_ID_PAYLOAD_KEY] for point in points), key=str)


# The scope predicate every scoped read has to carry.
SCOPE = models.Filter(
    should=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value="alice")),
        models.IsEmptyCondition(is_empty=models.PayloadField(key="user_id")),
    ]
)


class TestPayloadHasUserIdKey:
    """Pin the contract: ``user_id`` is a top-level payload key, not nested
    inside ``meta_data``. The payload index relies on this — moving it into
    a sub-dict would silently degrade reads from O(tenant) back to O(N)."""

    def test_user_id_key_constant_is_user_id(self):
        # Storage compatibility marker. If this changes, every previously
        # persisted row's user_id stops being readable by the filter.
        assert USER_ID_PAYLOAD_KEY == "user_id"

    def test_explicit_user_id_persisted_top_level(self, qdrant_db):
        qdrant_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        # Scroll the raw payload to verify the top-level key.
        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[USER_ID_PAYLOAD_KEY] == "alice"
        assert USER_ID_PAYLOAD_KEY not in points[0].payload["meta_data"]

    def test_none_user_id_persisted_as_null(self, qdrant_db):
        """Shared chunks store ``None`` in ``user_id``. The scope filter
        uses IsEmptyCondition, which matches both None and absent."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[USER_ID_PAYLOAD_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, qdrant_db):
        """Backwards-compatible: callers that never pass ``user_id`` get
        NULL (shared) — they're effectively opting out of isolation."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs())

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert points[0].payload[USER_ID_PAYLOAD_KEY] is None

    def test_create_indexes_user_id_as_a_tenant_keyword(self, qdrant_db):
        """``is_tenant=True`` is what makes per-user reads cheap; a plain
        keyword index would still be correct but would walk the whole graph.

        This is the one thing the real engine cannot express: Qdrant's local
        mode warns "Payload indexes have no effect in the local Qdrant" and
        drops the call, so ``real_qdrant_db`` would pass whether we asked for
        the index or not. Only the fake can see the request."""
        assert qdrant_db.client.payload_indexes == [
            {
                "field_name": "user_id",
                "field_schema": models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD,
                    is_tenant=True,
                ),
            }
        ]


class TestUserScopeFilter:
    """The scope-filter builder is small enough to unit-test directly. We
    catch the OR semantics and the shared-NULL pattern without spinning
    up the DB at all."""

    def test_none_returns_no_filter(self, qdrant_db):
        assert qdrant_db._user_scope_filter(None) is None

    def test_alice_filter_ors_her_own_id_with_the_shared_bucket(self, qdrant_db):
        # OR ("should") between: user_id == alice  OR  is_empty(user_id).
        # Compared as a whole so the field key and the value are both pinned.
        assert qdrant_db._user_scope_filter("alice") == SCOPE

    def test_merge_with_no_base_returns_scope_unchanged(self, qdrant_db):
        scope = qdrant_db._user_scope_filter("alice")
        assert qdrant_db._merge_filters(None, scope) is scope

    def test_merge_with_no_scope_returns_base_unchanged(self, qdrant_db):
        base = models.Filter(must=[models.FieldCondition(key="meta_data.tag", match=models.MatchValue(value="x"))])
        assert qdrant_db._merge_filters(base, None) is base

    def test_merge_nests_both_under_must(self, qdrant_db):
        """The scope is an OR, so it cannot be flattened into the caller's
        ``must`` list without widening the metadata filter."""
        base = models.Filter(must=[models.FieldCondition(key="meta_data.tag", match=models.MatchValue(value="x"))])

        merged = qdrant_db._merge_filters(base, qdrant_db._user_scope_filter("alice"))

        assert merged == models.Filter(must=[base, SCOPE])


class TestSearchIsolationContract:
    """The load-bearing test: alice's search returns her chunks plus
    shared chunks, but never bob's. This is what makes K2 actually work."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_alice_sees_her_own_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        """The isolation contract. If this fails the whole feature is
        broken — alice would be retrieving bob's confidential chunks."""
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        # Belt and braces: also check content.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated_db):
        """``user_id=None`` at search time means no scope — admin view."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "bob-salary" in names
        assert "company-holidays" in names

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="carol")
        assert {d.name for d in results} == {"company-holidays"}

    def test_empty_string_owner_stays_scoped(self, populated_db):
        """Only ``None`` means "no scope". An empty string is an owner like any
        other, so it reads its own (empty) bucket plus the shared one — never
        another owner's. Chroma routes ``""`` to the base collection and LanceDB
        emits ``user_id = ''``; this keeps Qdrant restrictive on the same input."""
        results = populated_db.search(query="anything", limit=10, user_id="")

        names = {d.name for d in results}
        assert "bob-salary" not in names
        assert "alice-salary" not in names


class TestQueryFilterShape:
    """The Filter the backend actually sent to the server."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        return qdrant_db

    def test_scoped_search_sends_the_scope_filter(self, populated_db):
        populated_db.search(query="salary", limit=10, user_id="alice")

        assert populated_db.client.query_filters[-1] == SCOPE

    def test_unscoped_search_sends_no_filter(self, populated_db):
        populated_db.search(query="salary", limit=10, user_id=None)

        assert populated_db.client.query_filters[-1] is None

    def test_scope_composes_with_metadata_filters(self, populated_db):
        """The metadata filter and the scope are ANDed; the scope's OR must
        stay nested so it cannot widen the metadata predicate."""
        populated_db.search(query="salary", limit=10, filters={"team": "eng"}, user_id="alice")

        expected_base = models.Filter(
            must=[models.FieldCondition(key="meta_data.team", match=models.MatchValue(value="eng"))]
        )
        assert populated_db.client.query_filters[-1] == models.Filter(must=[expected_base, SCOPE])

    def test_metadata_filter_and_scope_both_bind(self, populated_db):
        """Behaviour behind the shape above: alice's other-team chunk and
        bob's same-team chunk are both excluded."""
        populated_db.insert(content_hash="ha2", documents=_alice_docs(), filters={"team": "eng"}, user_id="alice")
        populated_db.insert(content_hash="hb", documents=_bob_docs(), filters={"team": "eng"}, user_id="bob")

        results = populated_db.search(query="salary", limit=10, filters={"team": "eng"}, user_id="alice")

        assert {d.name for d in results} == {"alice-salary"}


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the
    delete to the caller's chunks — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    Qdrant scopes via a ``must`` filter combining ``content_id`` AND
    ``user_id`` on the server side.
    """

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Two users own chunks under the SAME content_id 'doc-1'. The
        adversarial scenario — Bob guesses the id and tries to delete it.
        Without ``user_id`` scoping he'd wipe Alice's row too."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        qdrant_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        qdrant_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return qdrant_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob asks to delete 'doc-1' under his own scope — Alice's chunk
        must remain."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert _owners(populated_db) == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_scoped_delete_ands_the_owner_into_the_filter(self, populated_db):
        """Both conditions sit in ``must``: content_id AND owner. Losing the
        owner arm turns a scoped delete into a cross-tenant wipe."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert populated_db.client.delete_filters[-1] == models.Filter(
            must=[
                models.FieldCondition(key="content_id", match=models.MatchValue(value="doc-1")),
                models.FieldCondition(key="user_id", match=models.MatchValue(value="bob")),
            ]
        )

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        assert _owners(populated_db) == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners.
        Pin it so we notice if the default semantics change."""
        populated_db.delete_by_content_id("doc-1", user_id=None)

        assert populated_db.get_count() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, populated_db):
        """Carol has no chunks. Her scoped delete of doc-1 is a no-op."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")
        assert populated_db.get_count() == 2


class TestContentHashExistsScope:
    """The dedup existence gate binds the owner into its count filter, so
    another owner's identical upload is never judged a duplicate —
    ``skip_if_exists`` would otherwise deny the second owner a copy of content
    they cannot retrieve. ``None`` binds ``is_empty(user_id)``: it is the guard
    half of the pair whose other half deletes the shared bucket, and the two
    halves have to address the same points."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """One hash Bob owns, a different one in the shared bucket."""
        qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_owner_sees_his_own_hash(self, populated_db):
        assert populated_db.content_hash_exists("hb", user_id="bob") is True

    def test_another_owners_hash_is_not_a_duplicate(self, populated_db):
        """Alice uploading the bytes Bob already holds must not be skipped —
        she has no points of her own to retrieve."""
        assert populated_db.content_hash_exists("hb", user_id="alice") is False

    def test_the_shared_hash_is_not_the_owners_duplicate(self, populated_db):
        """Same rule for the shared bucket: those points are not Bob's."""
        assert populated_db.content_hash_exists("hs", user_id="bob") is False

    def test_a_privately_owned_hash_is_not_in_the_shared_bucket(self, populated_db):
        """The regression. ``None`` used to count every owner's points, so a hash
        only Bob owns read as a duplicate for the shared bucket — and a later
        shared publish under ``skip_if_exists`` was swallowed, leaving the shared
        bucket without the content it was asked to hold."""
        assert populated_db.content_hash_exists("hb", user_id=None) is False

    def test_unscoped_check_binds_the_shared_bucket_condition(self, populated_db):
        """The filter behind it, the same one ``_delete_by_content_hash`` sends
        for ``None``."""
        populated_db.content_hash_exists("hb", user_id=None)

        assert populated_db.client.count_filters[-1] == models.Filter(
            must=[
                models.FieldCondition(key="content_hash", match=models.MatchValue(value="hb")),
                models.IsEmptyCondition(is_empty=models.PayloadField(key="user_id")),
            ]
        )

    def test_unscoped_check_sees_the_shared_bucket_too(self, populated_db):
        assert populated_db.content_hash_exists("hs", user_id=None) is True

    def test_shared_publish_survives_a_private_holder(self, populated_db):
        """The user-visible half: the shared publish is not skipped, so the shared
        bucket ends up holding Bob's hash too and Bob's own point survives."""
        if not populated_db.content_hash_exists("hb", user_id=None):
            populated_db.insert(content_hash="hb", documents=_bob_docs(), user_id=None)

        assert populated_db.content_hash_exists("hb", user_id=None) is True
        # The pre-existing shared point, the newly published one, and Bob's.
        assert _owners(populated_db) == [None, None, "bob"]


class TestUpsertDedupScope:
    """``upsert`` deletes any stored copy of the same ``content_hash`` before
    re-inserting. Both halves of that pair — the existence gate and the delete
    — have to bind the writing owner, otherwise a user upserting content the
    admin already shared wipes the shared points out from under everyone.
    """

    @pytest.fixture
    def shared_db(self, qdrant_db):
        """One admin upload with no owner: the shared bucket every user reads."""
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_scoped_upsert_of_identical_content_keeps_the_shared_point(self, shared_db):
        """The keystone. Bob upserts byte-identical content under his own
        scope — the company-wide document must survive."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert _owners(shared_db) == [None, "bob"]

    def test_another_owner_can_still_retrieve_the_shared_doc(self, shared_db):
        """The user-visible half of the assertion above: Alice's retrieval of
        the org-wide document still works after Bob's upsert. Bob's own copy
        is filtered out, so a single point comes back."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        results = shared_db.search(query="anything", limit=10, user_id="alice")
        assert [d.name for d in results] == ["company-holidays"]

    def test_two_owners_of_identical_content_get_distinct_point_ids(self, shared_db):
        """Point ids are deterministic, so without the owner folded in Bob's
        write would land on the shared point's id and overwrite it — the same
        destruction the scoped delete exists to prevent."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert len(shared_db.client.points) == 2

    def test_underscored_base_id_cannot_collide_with_a_different_split(self, qdrant_db):
        """The base id is collapsed to a fixed-length digest before the owner is
        folded in. Without that collapse the '_' boundary moves and
        ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') join to one point id,
        letting one owner overwrite the other's point."""
        assert qdrant_db._scoped_doc_id("doc", "1", "a_lice") != qdrant_db._scoped_doc_id("doc", "1_a", "lice")
        # whatever the caller passes, the owner is always folded into a fixed-length digest
        assert len(qdrant_db._scoped_doc_id("doc_1_2_3", "hs", None)) == 32

    def test_scoped_dedup_delete_ands_the_owner_into_the_filter(self, shared_db):
        """Bob's second upsert of his own content deletes only his points:
        both conditions sit in ``must``, content_hash AND owner."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert shared_db.client.delete_filters[-1] == models.Filter(
            must=[
                models.FieldCondition(key="content_hash", match=models.MatchValue(value="hs")),
                models.FieldCondition(key="user_id", match=models.MatchValue(value="bob")),
            ]
        )
        assert _owners(shared_db) == [None, "bob"]

    def test_shared_reupsert_only_deletes_the_shared_bucket(self, shared_db):
        """The mirror image: an admin re-upsert of content Bob also holds must
        leave Bob's points alone. ``None`` binds is_empty(user_id) rather than
        every owner — the shared-bucket semantics pgvector and LanceDB give it."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id=None)

        assert shared_db.client.delete_filters[-1] == models.Filter(
            must=[
                models.FieldCondition(key="content_hash", match=models.MatchValue(value="hs")),
                models.IsEmptyCondition(is_empty=models.PayloadField(key="user_id")),
            ]
        )
        assert _owners(shared_db) == [None, "bob"]


class TestDeleteByContentHashScope:
    """``_delete_by_content_hash`` scoped to an owner clears only that owner;
    None clears ONLY the shared bucket, never another owner's identical points."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """The same content hash stored three times over — shared, Alice's and
        Bob's — which is what a re-upload of an org-wide document looks like."""
        qdrant_db.insert(content_hash="h", documents=_shared_docs(), user_id=None)
        qdrant_db.insert(content_hash="h", documents=_shared_docs(), user_id="alice")
        qdrant_db.insert(content_hash="h", documents=_shared_docs(), user_id="bob")
        return qdrant_db

    def test_scoped_delete_matches_owner_only(self, populated_db):
        populated_db._delete_by_content_hash("h", user_id="alice")

        assert _owners(populated_db) == [None, "bob"]

    def test_none_delete_matches_shared_bucket_only(self, populated_db):
        populated_db._delete_by_content_hash("h", user_id=None)

        assert _owners(populated_db) == ["alice", "bob"]

    def test_delete_for_an_owner_with_no_points_is_a_no_op(self, populated_db):
        """Carol has never written. Her scoped delete leaves every point alone."""
        populated_db._delete_by_content_hash("h", user_id="carol")

        assert populated_db.get_count() == 3


class TestEmptyStringDeleteScope:
    """``delete_by_content_id`` guarded on ``if user_id:``, so an empty string
    dropped the owner predicate and matched every owner's rows."""

    def test_empty_string_owner_does_not_delete_other_owners(self, qdrant_db):
        # Both owners hold the content_id the empty-string caller asks to delete,
        # so the guard is the only thing standing between the call and their points.
        alice, bob = _alice_docs()[0], _bob_docs()[0]
        alice.content_id = "shared-content-id"
        bob.content_id = "shared-content-id"
        qdrant_db.insert(content_hash="ha", documents=[alice], user_id="alice")
        qdrant_db.insert(content_hash="hb", documents=[bob], user_id="bob")

        qdrant_db.delete_by_content_id("shared-content-id", user_id="")

        assert {d.name for d in qdrant_db.search("anything", limit=10, user_id="alice")} == {"alice-salary"}
        assert {d.name for d in qdrant_db.search("anything", limit=10, user_id="bob")} == {"bob-salary"}


class TestRealEngineIsolation:
    """The same contract, driven end to end against a real in-memory Qdrant.

    Everything above asserts on the Filter the backend built; the fake evaluates
    it, but it also accepts it unconditionally. These tests are what prove the
    engine accepts those filters at all — a malformed ``models.Filter`` passes
    the fake and is rejected by a server. The shared embedding the mock embedder
    returns makes every point equidistant, so anything that comes back or does
    not come back here is the scope filter's doing.
    """

    @pytest.fixture
    def populated_db(self, real_qdrant_db):
        """Three points: one alice, one bob, one shared (NULL)."""
        real_qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        real_qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        real_qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return real_qdrant_db

    def test_owner_is_persisted_as_a_top_level_payload_key(self, populated_db):
        assert _owners(populated_db) == [None, "alice", "bob"]

    def test_alice_sees_her_own_and_the_shared_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="alice")

        assert {d.name for d in results} == {"alice-salary", "company-holidays"}

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        """The isolation contract. If this fails the whole feature is broken —
        alice would be retrieving bob's confidential chunks."""
        results = populated_db.search(query="salary", limit=10, user_id="alice")

        for d in results:
            assert "Bob's salary" not in d.content

    def test_admin_sees_everything(self, populated_db):
        """``user_id=None`` at search time means no scope — admin view."""
        results = populated_db.search(query="anything", limit=10, user_id=None)

        assert {d.name for d in results} == {"alice-salary", "bob-salary", "company-holidays"}

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="carol")

        assert {d.name for d in results} == {"company-holidays"}

    def test_scoped_delete_leaves_the_shared_chunk(self, populated_db):
        """Bob deletes under his own scope: the org-wide document survives and
        stays retrievable by everyone. His scoped attempt at the shared hash is
        a no-op — a caller may read the shared bucket but not delete out of it."""
        populated_db._delete_by_content_hash("hs", user_id="bob")
        populated_db._delete_by_content_hash("hb", user_id="bob")

        assert _owners(populated_db) == [None, "alice"]
        assert {d.name for d in populated_db.search("anything", limit=10, user_id="alice")} == {
            "alice-salary",
            "company-holidays",
        }

    def test_unscoped_delete_removes_the_shared_chunk(self, populated_db):
        """The mirror: ``None`` addresses the shared bucket, so the org-wide
        document goes and both owners' points stay."""
        populated_db._delete_by_content_hash("hs", user_id=None)

        assert _owners(populated_db) == ["alice", "bob"]

    def test_two_owners_of_identical_content_get_distinct_point_ids(self, real_qdrant_db):
        """Point ids are deterministic, so without the owner folded in bob's
        write would land on alice's id and overwrite it."""
        real_qdrant_db.insert(content_hash="h", documents=_shared_docs(), user_id="alice")
        real_qdrant_db.insert(content_hash="h", documents=_shared_docs(), user_id="bob")

        assert real_qdrant_db.get_count() == 2
        assert _owners(real_qdrant_db) == ["alice", "bob"]

    def test_scoped_upsert_of_identical_content_keeps_the_shared_point(self, real_qdrant_db):
        """The keystone, against the engine: bob upserts byte-identical content
        under his own scope and the company-wide document must survive."""
        real_qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        real_qdrant_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert _owners(real_qdrant_db) == [None, "bob"]

    def test_content_hash_gate_binds_the_shared_bucket(self, populated_db):
        """``IsEmptyCondition`` inside a ``must`` list is the filter the fake can
        only echo back. The engine has to accept and evaluate it: bob's private
        hash is not in the shared bucket, the shared one is."""
        assert populated_db.content_hash_exists("hb", user_id="bob") is True
        assert populated_db.content_hash_exists("hb", user_id=None) is False
        assert populated_db.content_hash_exists("hs", user_id=None) is True
