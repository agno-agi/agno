"""Redis per-user RAG isolation contract.

The RedisDB adapter stores a chunk's owner in a top-level ``user_id`` TAG
field. Scoped reads apply an owner-OR-shared TAG scope so admin-uploaded
shared content (stored under the ``__shared__`` sentinel) stays discoverable;
unscoped (admin) reads apply no scope. The deterministic id folds the owner
in so two users uploading identical content never collide.

The redis client and the redisvl ``SearchIndex`` are patched so no server is
contacted. We assert on the values the adapter produces — the ``user_id`` tag
written on each hash, the owner-folded doc id, and the ``FilterExpression``
built for every scoped search / dedup / delete.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256
from agno.vectordb.redis.redisdb import RedisDB
from agno.vectordb.search import SearchType

USER_ID_FIELD = RedisDB.USER_ID_FIELD
SHARED = RedisDB.SHARED_OWNER_TAG


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

    dimensions = 8
    enable_batch = False

    def get_embedding(self, text):
        vector = [0.0] * self.dimensions
        vector[abs(hash(text)) % self.dimensions] = 1.0
        return vector

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


def _embedded(name: str, content: str, content_id: str = None, doc_id: str = None) -> Document:
    """A Document carrying a precomputed embedding."""
    doc = Document(name=name, content=content)
    if doc_id is not None:
        doc.id = doc_id
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


@pytest.fixture
def redis_db():
    """A RedisDB whose redis client and redisvl ``SearchIndex`` are patched."""
    with (
        patch("agno.vectordb.redis.redisdb.Redis") as mock_redis,
        patch("agno.vectordb.redis.redisdb.SearchIndex") as mock_index_cls,
    ):
        mock_redis.from_url.return_value = MagicMock()
        index = MagicMock()
        index.query.return_value = []
        mock_index_cls.return_value = index

        db = RedisDB(
            index_name="iso_test",
            redis_url="redis://patched.invalid:6379",
            embedder=_DeterministicEmbedder(),
            search_type=SearchType.vector,
        )
        db.index = index
        yield db


def _loaded_docs(db):
    """The list of hash dicts passed to the most recent ``index.load``."""
    assert db.index.load.called, "index.load was never called"
    return db.index.load.call_args.args[0]


def _queried_filter(db):
    """str() of the FilterExpression on the most recent ``index.query``."""
    assert db.index.query.called, "index.query was never called"
    query = db.index.query.call_args.args[0]
    return str(query.filter)


class TestWriteStampsOwner:
    """``user_id`` is a top-level TAG on every hash. Shared chunks store the
    ``__shared__`` sentinel so the owner-OR-shared scope can match them."""

    def test_isolation_constants(self):
        # Storage-compatibility markers: changing either orphans the scope on
        # every previously persisted row.
        assert RedisDB.USER_ID_FIELD == "user_id"
        assert RedisDB.SHARED_OWNER_TAG == "__shared__"

    def test_explicit_user_id_persisted(self, redis_db):
        redis_db.insert(content_hash="h1", documents=[_embedded("alice-salary", "Alice secret 180k.")], user_id="alice")
        docs = _loaded_docs(redis_db)
        assert len(docs) == 1
        assert docs[0][USER_ID_FIELD] == "alice"

    def test_none_user_id_stamps_shared_sentinel(self, redis_db):
        redis_db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")], user_id=None)
        assert _loaded_docs(redis_db)[0][USER_ID_FIELD] == SHARED

    def test_user_id_omitted_defaults_to_shared(self, redis_db):
        redis_db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")])
        assert _loaded_docs(redis_db)[0][USER_ID_FIELD] == SHARED

    def test_caller_meta_data_cannot_spoof_owner(self, redis_db):
        """``user_id`` / ``id`` in caller meta_data must not override the
        adapter-stamped owner or the owner-folded key."""
        doc = Document(name="d", content="c", meta_data={"user_id": "attacker", "id": "evil"})
        doc.embedding = _DeterministicEmbedder().get_embedding("c")
        redis_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        loaded = _loaded_docs(redis_db)[0]
        assert loaded[USER_ID_FIELD] == "alice"
        assert loaded["id"] != "evil"


class TestIdFolding:
    """The deterministic key folds the owner in, so two users uploading
    byte-identical content get DISTINCT keys and cannot clobber each other.
    The shared bucket keeps the legacy (unfolded) id."""

    _SAME = "The quarterly figure is identical for both owners."

    def test_identical_content_two_owners_get_distinct_keys(self, redis_db):
        redis_db.insert(content_hash="h", documents=[_embedded("a", self._SAME)], user_id="alice")
        alice_key = _loaded_docs(redis_db)[0]["id"]
        redis_db.index.load.reset_mock()
        redis_db.insert(content_hash="h", documents=[_embedded("b", self._SAME)], user_id="bob")
        bob_key = _loaded_docs(redis_db)[0]["id"]
        assert alice_key != bob_key

    def test_scoped_key_is_owner_folded_hash(self, redis_db):
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id="alice")
        assert _loaded_docs(redis_db)[0]["id"] == hash_string_sha256(f"{hash_string_sha256('doc-1')}_alice")

    def test_shared_keeps_legacy_id(self, redis_db):
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id=None)
        assert _loaded_docs(redis_db)[0]["id"] == "doc-1"

    def test_owner_boundary_cannot_be_shifted(self, redis_db):
        """The base id is caller-controlled, so it is collapsed to a fixed-length
        digest before the owner is folded in. Without that, ("doc_1", "alice") and
        ("doc", "1_alice") both join to "doc_1_alice" and land on ONE key — and
        every agno chunk id ends in "_<n>", so a caller passing user_id="1_alice"
        overwrites alice's chunk 1."""
        assert redis_db._scoped_doc_id("doc_1", "alice") != redis_db._scoped_doc_id("doc", "1_alice")

    def test_shifted_boundary_write_does_not_overwrite_the_owner(self, redis_db):
        """The consequence on the write path: alice's chunk key and the crafted
        owner's key are different keys, so neither write clobbers the other."""
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc_1")], user_id="alice")
        alice_key = _loaded_docs(redis_db)[0]["id"]
        redis_db.index.load.reset_mock()
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc")], user_id="1_alice")
        assert _loaded_docs(redis_db)[0]["id"] != alice_key


class TestReadScope:
    """A scoped search filters to the caller's own chunks OR the shared bucket
    and never another user's; admin (``None``) applies no scope. With a mocked
    index the FilterExpression carried by the query IS the contract."""

    def test_user_scope_filter_builder(self, redis_db):
        assert str(redis_db._user_scope_filter("alice")) == "@user_id:{alice|__shared__}"
        assert redis_db._user_scope_filter(None) is None

    def test_scoped_search_builds_own_or_shared(self, redis_db):
        redis_db.search(query="secret salary", limit=10, user_id="alice")
        assert _queried_filter(redis_db) == "@user_id:{alice|__shared__}"

    def test_admin_search_has_no_scope(self, redis_db):
        redis_db.search(query="secret salary", limit=10, user_id=None)
        # A wildcard filter == no owner scope; admin sees everything.
        assert _queried_filter(redis_db) == "*"

    async def test_async_search_scopes_identically(self, redis_db):
        await redis_db.async_search(query="secret salary", limit=10, user_id="alice")
        assert _queried_filter(redis_db) == "@user_id:{alice|__shared__}"


class TestContentHashExists:
    """``content_hash_exists`` is the guard half of the upsert dedup pair, so it
    has to mean exactly what the dedup delete means: a set owner checks that
    owner's chunks, ``None`` checks the shared bucket alone. A ``None`` matching
    any owner would let one tenant's private copy skip a shared publish."""

    def test_scoped_check_ands_the_owner(self, redis_db):
        redis_db.content_hash_exists("h1", user_id="alice")
        assert _queried_filter(redis_db) == "(@content_hash:{h1} @user_id:{alice})"

    def test_none_check_scopes_to_the_shared_bucket(self, redis_db):
        redis_db.content_hash_exists("h1", user_id=None)
        assert _queried_filter(redis_db) == "(@content_hash:{h1} @user_id:{__shared__})"

    def test_check_matches_the_dedup_delete_bucket(self, redis_db):
        """The two halves are one guard: the check reuses ``_dedupe_filter``, so
        they can never drift onto different buckets."""
        for owner in ("alice", None):
            redis_db.content_hash_exists("h1", user_id=owner)
            assert _queried_filter(redis_db) == str(redis_db._dedupe_filter("h1", owner))

    def test_none_check_does_not_see_a_privately_owned_row(self, redis_db):
        """Alice privately holds this content. If ``None`` matched her chunk, a
        shared publish of the same bytes would be judged a duplicate and silently
        skipped, and the shared bucket would never receive it."""
        redis_db.index.query.side_effect = lambda query: (
            [{"id": "k"}] if "@user_id:{alice}" in str(query.filter) else []
        )
        assert redis_db.content_hash_exists("h1", user_id=None) is False
        assert redis_db.content_hash_exists("h1", user_id="alice") is True

    def test_none_check_sees_the_shared_row(self, redis_db):
        redis_db.index.query.side_effect = lambda query: (
            [{"id": "k"}] if f"@user_id:{{{SHARED}}}" in str(query.filter) else []
        )
        assert redis_db.content_hash_exists("h1", user_id=None) is True


class TestScopedDedupe:
    """The upsert dedup-delete is scoped to the writing owner's bucket: a
    scoped upsert dedups only that owner's chunks, a shared upsert dedups only
    the shared bucket — one can never evict the other's identical content."""

    def test_scoped_upsert_dedup_scoped_to_owner(self, redis_db):
        redis_db.upsert(content_hash="hc", documents=[_embedded("owned", "same")], user_id="alice")
        assert _queried_filter(redis_db) == "(@content_hash:{hc} @user_id:{alice})"

    def test_shared_upsert_dedup_scoped_to_shared(self, redis_db):
        redis_db.upsert(content_hash="hc", documents=[_embedded("shared", "same")], user_id=None)
        assert _queried_filter(redis_db) == "(@content_hash:{hc} @user_id:{__shared__})"


class TestScopedDelete:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to
    the caller's chunks. A scoped delete matches the owner EXACTLY (it must
    NOT reach the shared bucket); ``None`` deletes across all owners."""

    def test_scoped_delete_restricts_to_owner(self, redis_db):
        redis_db.delete_by_content_id("cid1", user_id="alice")
        # Owner-only: no ``|__shared__`` alternation here, unlike a read scope.
        assert _queried_filter(redis_db) == "@content_id:{cid1} @user_id:{alice}"

    def test_unscoped_delete_spans_all_owners(self, redis_db):
        redis_db.delete_by_content_id("cid1", user_id=None)
        assert _queried_filter(redis_db) == "@content_id:{cid1}"


class TestUserIdValidation:
    """Reserved / structurally unsafe owner values are rejected up front so a
    caller can neither impersonate the shared bucket nor break the TAG scope."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # an owner tag no scope clause can match
            RedisDB.SHARED_OWNER_TAG,  # shared-bucket impersonation
            RedisDB.MATCH_ALL_TAG,  # breaks a match-all query
            "alice*",  # wildcard matches other owners
            "alice?",  # wildcard matches other owners
            "alice{1}",  # brace can never be matched by a scope clause
            "a\x1fb",  # separator indexes one value as several tags
            "alice|bob",  # '|' is the TAG union operator — reads another owner
            " alice",  # leading whitespace is trimmed by the index and collapses onto 'alice'
            "alice ",  # trailing whitespace collapses onto 'alice'
        ],
    )
    def test_rejects_unsafe_user_id(self, redis_db, bad):
        with pytest.raises(ValueError):
            redis_db._validate_user_id(bad)
        # And the rejection is enforced on the write path, not just the helper.
        with pytest.raises(ValueError):
            redis_db.insert(content_hash="h", documents=[_embedded("a", "x")], user_id=bad)
        assert not redis_db.index.load.called

    def test_none_is_allowed(self, redis_db):
        redis_db._validate_user_id(None)

    async def test_async_insert_rejects_unsafe_user_id(self, redis_db):
        with pytest.raises(ValueError):
            await redis_db.async_insert(content_hash="h", documents=[_embedded("a", "x")], user_id="")
