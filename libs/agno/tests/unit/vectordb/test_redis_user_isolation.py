"""Redis per-user RAG isolation contract.

The RedisDB adapter stores a chunk's owner in a top-level ``user_id`` TAG
field. Scoped reads apply an owner-OR-shared TAG scope so admin-uploaded
shared content (stored under the ``__shared__`` sentinel) stays discoverable;
unscoped (admin) reads apply no scope. The deterministic id folds the owner
in so two users uploading identical content never collide.

This is a TRUE unit test: the redis client and the redisvl ``SearchIndex``
are patched so no server (RediSearch) is ever contacted. Because there is no
server to retrieve from, the isolation contract is asserted on the VALUES the
adapter produces -- the ``user_id`` tag written on each hash, the scoped doc
id (key), and the string form of the redisvl ``FilterExpression`` built for
every scoped search / dedup / delete. Those strings ARE the isolation: an
own-OR-shared scope excludes bob by construction, an owner-folded key stops
one writer clobbering another, and a scoped delete filter that names one
owner cannot reach another's chunks.
"""

from unittest.mock import MagicMock, patch

import pytest

# Skip cleanly only if the optional dependency isn't installed. The test never
# needs a running server -- everything below is patched.
pytest.importorskip("redisvl")

from agno.knowledge.document import Document  # noqa: E402
from agno.utils.string import hash_string_sha256  # noqa: E402
from agno.vectordb.redis.redisdb import RedisDB  # noqa: E402
from agno.vectordb.search import SearchType  # noqa: E402

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
    """A Document carrying a precomputed embedding so ``insert`` never has to
    round-trip an embedder."""
    doc = Document(name=name, content=content)
    if doc_id is not None:
        doc.id = doc_id
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


@pytest.fixture
def db():
    """A RedisDB whose redis client and redisvl ``SearchIndex`` are both
    patched -- no connection is ever attempted. ``index.query`` returns an
    empty result so the delete / dedup query loops are harmless; we assert on
    the FilterExpression each call carries, not on any retrieved rows."""
    with (
        patch("agno.vectordb.redis.redisdb.Redis") as mock_redis,
        patch("agno.vectordb.redis.redisdb.SearchIndex") as mock_index_cls,
    ):
        mock_redis.from_url.return_value = MagicMock()
        index = MagicMock()
        index.query.return_value = []
        mock_index_cls.return_value = index

        database = RedisDB(
            index_name="iso_test",
            redis_url="redis://patched.invalid:6379",
            embedder=_DeterministicEmbedder(),
            search_type=SearchType.vector,
        )
        # The patched SearchIndex(...) call returned our mock; pin it explicitly.
        database.index = index
        yield database


def _loaded_docs(db):
    """The list of hash dicts passed to the most recent ``index.load``."""
    assert db.index.load.called, "index.load was never called"
    return db.index.load.call_args.args[0]


def _queried_filter(db):
    """str() of the FilterExpression on the most recent ``index.query``.

    Works for both VectorQuery (search) and FilterQuery (dedup / delete) --
    both expose a ``.filter`` whose str() is the raw RediSearch clause.
    """
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

    def test_explicit_user_id_persisted(self, db):
        db.insert(content_hash="h1", documents=[_embedded("alice-salary", "Alice secret 180k.")], user_id="alice")
        docs = _loaded_docs(db)
        assert len(docs) == 1
        assert docs[0][USER_ID_FIELD] == "alice"

    def test_none_user_id_stamps_shared_sentinel(self, db):
        """Shared chunks store the sentinel, not an empty/absent value -- a
        bare TAG could not be matched by the owner-OR-shared clause."""
        db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")], user_id=None)
        assert _loaded_docs(db)[0][USER_ID_FIELD] == SHARED

    def test_user_id_omitted_defaults_to_shared(self, db):
        db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")])
        assert _loaded_docs(db)[0][USER_ID_FIELD] == SHARED

    def test_caller_meta_data_cannot_spoof_owner(self, db):
        """``user_id`` / ``id`` in caller meta_data must not override the
        adapter-stamped owner or the owner-folded key."""
        doc = Document(name="d", content="c", meta_data={"user_id": "attacker", "id": "evil"})
        doc.embedding = _DeterministicEmbedder().get_embedding("c")
        db.insert(content_hash="h1", documents=[doc], user_id="alice")
        loaded = _loaded_docs(db)[0]
        assert loaded[USER_ID_FIELD] == "alice"
        assert loaded["id"] != "evil"


class TestIdFolding:
    """The deterministic key folds the owner in, so two users uploading
    byte-identical content get DISTINCT keys and cannot clobber each other.
    The shared bucket keeps the legacy (unfolded) id."""

    _SAME = "The quarterly figure is identical for both owners."

    def test_identical_content_two_owners_get_distinct_keys(self, db):
        db.insert(content_hash="h", documents=[_embedded("a", self._SAME)], user_id="alice")
        alice_key = _loaded_docs(db)[0]["id"]
        db.index.load.reset_mock()
        db.insert(content_hash="h", documents=[_embedded("b", self._SAME)], user_id="bob")
        bob_key = _loaded_docs(db)[0]["id"]
        assert alice_key != bob_key

    def test_scoped_key_is_owner_folded_hash(self, db):
        """A scoped write hashes ``<base_id>_<user_id>``."""
        db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id="alice")
        assert _loaded_docs(db)[0]["id"] == hash_string_sha256("doc-1_alice")

    def test_shared_keeps_legacy_id(self, db):
        """A shared (``user_id=None``) write is not folded -- it round-trips on
        the plain document id."""
        db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id=None)
        assert _loaded_docs(db)[0]["id"] == "doc-1"


class TestReadScope:
    """A scoped search filters to the caller's own chunks OR the shared bucket
    and never another user's; admin (``None``) applies no scope. With a mocked
    index the FilterExpression carried by the query IS the contract."""

    def test_user_scope_filter_builder(self, db):
        # The small builder is worth pinning directly.
        assert str(db._user_scope_filter("alice")) == "@user_id:{alice|__shared__}"
        assert db._user_scope_filter(None) is None

    def test_scoped_search_builds_own_or_shared(self, db):
        db.search(query="secret salary", limit=10, user_id="alice")
        # Own OR shared -- bob is excluded by construction.
        assert _queried_filter(db) == "@user_id:{alice|__shared__}"

    def test_admin_search_has_no_scope(self, db):
        db.search(query="secret salary", limit=10, user_id=None)
        # A wildcard filter == no owner scope; admin sees everything.
        assert _queried_filter(db) == "*"

    async def test_async_search_scopes_identically(self, db):
        # async_search delegates to the sync path via asyncio.to_thread.
        await db.async_search(query="secret salary", limit=10, user_id="alice")
        assert _queried_filter(db) == "@user_id:{alice|__shared__}"


class TestScopedDedupe:
    """The upsert dedup-delete is scoped to the writing owner's bucket: a
    scoped upsert dedups only that owner's chunks, a shared upsert dedups only
    the shared bucket -- one can never evict the other's identical content."""

    def test_scoped_upsert_dedup_scoped_to_owner(self, db):
        db.upsert(content_hash="hc", documents=[_embedded("owned", "same")], user_id="alice")
        # The FilterQuery driving the pre-delete names the owner, not shared.
        assert _queried_filter(db) == "(@content_hash:{hc} @user_id:{alice})"

    def test_shared_upsert_dedup_scoped_to_shared(self, db):
        db.upsert(content_hash="hc", documents=[_embedded("shared", "same")], user_id=None)
        # A shared re-ingest touches only the shared bucket, leaving owned rows.
        assert _queried_filter(db) == "(@content_hash:{hc} @user_id:{__shared__})"


class TestScopedDelete:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to
    the caller's chunks. Per the adapter contract a scoped delete matches the
    owner EXACTLY (it must NOT reach the shared bucket -- wiping org content is
    a breach). ``None`` deletes across all owners (legacy/admin)."""

    def test_scoped_delete_restricts_to_owner(self, db):
        db.delete_by_content_id("cid1", user_id="alice")
        # Owner-only: no ``|__shared__`` alternation here, unlike a read scope.
        assert _queried_filter(db) == "@content_id:{cid1} @user_id:{alice}"

    def test_unscoped_delete_spans_all_owners(self, db):
        db.delete_by_content_id("cid1", user_id=None)
        assert _queried_filter(db) == "@content_id:{cid1}"


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
        ],
    )
    def test_rejects_unsafe_user_id(self, db, bad):
        with pytest.raises(ValueError):
            db._validate_user_id(bad)
        # And the rejection is enforced on the write path, not just the helper.
        with pytest.raises(ValueError):
            db.insert(content_hash="h", documents=[_embedded("a", "x")], user_id=bad)
        assert not db.index.load.called

    def test_none_is_allowed(self, db):
        db._validate_user_id(None)

    async def test_async_insert_rejects_unsafe_user_id(self, db):
        # Validation runs before any async index is created, so this needs no
        # async connection either.
        with pytest.raises(ValueError):
            await db.async_insert(content_hash="h", documents=[_embedded("a", "x")], user_id="")
