"""Redis per-user RAG isolation contract.

Owner lives in a top-level ``user_id`` TAG field; the ``__shared__`` sentinel is the shared bucket.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256
from agno.vectordb.search import SearchType

from .conftest import DeterministicEmbedder

# The adapter import is deferred past the skip: ``redisdb`` raises ImportError without redisvl.
pytest.importorskip("redisvl")

from agno.vectordb.redis.redisdb import RedisDb  # noqa: E402

USER_ID_FIELD = RedisDb.USER_ID_FIELD
SHARED = RedisDb.SHARED_OWNER_TAG


def _embedded(name: str, content: str, content_id: str = None, doc_id: str = None) -> Document:
    """A Document carrying a precomputed embedding."""
    doc = Document(name=name, content=content)
    if doc_id is not None:
        doc.id = doc_id
    doc.embedding = DeterministicEmbedder().get_embedding(content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


@pytest.fixture
def redis_db():
    """A RedisDb whose redis client and redisvl ``SearchIndex`` are patched."""
    with (
        patch("agno.vectordb.redis.redisdb.Redis") as mock_redis,
        patch("agno.vectordb.redis.redisdb.SearchIndex") as mock_index_cls,
    ):
        mock_redis.from_url.return_value = MagicMock()
        index = MagicMock()
        index.query.return_value = []
        mock_index_cls.return_value = index

        db = RedisDb(
            index_name="iso_test",
            redis_url="redis://patched.invalid:6379",
            embedder=DeterministicEmbedder(),
            search_type=SearchType.vector,
        )
        db.index = index
        # The mocked index cannot answer the live-schema probe, so prime the owner-field gate.
        db._owner_field_exists = True
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
    """``user_id`` is a top-level TAG on every hash."""

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
        """Caller meta_data must not override the adapter-stamped owner or the owner-folded key."""
        doc = Document(name="d", content="c", meta_data={"user_id": "attacker", "id": "evil"})
        doc.embedding = DeterministicEmbedder().get_embedding("c")
        redis_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        loaded = _loaded_docs(redis_db)[0]
        assert loaded[USER_ID_FIELD] == "alice"
        assert loaded["id"] != "evil"


class TestOwnerFoldedId:
    """The deterministic key folds the owner in, so identical content from two users lands on distinct keys."""

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
        """The caller-controlled base id is collapsed to a fixed-length digest before the owner is folded in."""
        assert redis_db._scoped_doc_id("doc_1", "alice") != redis_db._scoped_doc_id("doc", "1_alice")

    def test_shifted_boundary_does_not_overwrite_owner(self, redis_db):
        """On the write path the crafted owner lands on a different key, so neither write clobbers the other."""
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc_1")], user_id="alice")
        alice_key = _loaded_docs(redis_db)[0]["id"]
        redis_db.index.load.reset_mock()
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc")], user_id="1_alice")
        assert _loaded_docs(redis_db)[0]["id"] != alice_key


class TestSearchScope:
    """A scoped search sees the caller's own chunks or the shared bucket; ``None`` applies no scope."""

    def test_user_scope_filter_builder(self, redis_db):
        assert str(redis_db._user_scope_filter("alice")) == "@user_id:{alice|__shared__}"
        assert redis_db._user_scope_filter(None) is None

    def test_scoped_search_builds_own_or_shared(self, redis_db):
        redis_db.search(query="secret salary", limit=10, user_id="alice")
        assert _queried_filter(redis_db) == "@user_id:{alice|__shared__}"

    def test_admin_search_has_no_scope(self, redis_db):
        redis_db.search(query="secret salary", limit=10, user_id=None)
        # A wildcard filter means no owner scope.
        assert _queried_filter(redis_db) == "*"

    @pytest.mark.asyncio
    async def test_async_search_scopes_identically(self, redis_db):
        await redis_db.async_search(query="secret salary", limit=10, user_id="alice")
        assert _queried_filter(redis_db) == "@user_id:{alice|__shared__}"


class TestContentHashExistsScope:
    """The dedup guard checks the bucket the dedup delete clears: the owner's chunks, or shared for ``None``."""

    def test_scoped_check_ands_the_owner(self, redis_db):
        redis_db.content_hash_exists("h1", user_id="alice")
        assert _queried_filter(redis_db) == "(@content_hash:{h1} @user_id:{alice})"

    def test_none_check_scopes_to_the_shared_bucket(self, redis_db):
        redis_db.content_hash_exists("h1", user_id=None)
        assert _queried_filter(redis_db) == "(@content_hash:{h1} @user_id:{__shared__})"

    def test_check_matches_the_dedup_delete_bucket(self, redis_db):
        """The check reuses ``_dedupe_filter``, so guard and delete cannot drift onto different buckets."""
        for owner in ("alice", None):
            redis_db.content_hash_exists("h1", user_id=owner)
            assert _queried_filter(redis_db) == str(redis_db._dedupe_filter("h1", owner))

    def test_none_check_does_not_see_a_privately_owned_row(self, redis_db):
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


class TestUpsertDedupScope:
    """The upsert dedup-delete is scoped to the writing owner's bucket, so it cannot evict another owner's chunks."""

    def test_scoped_upsert_dedup_scoped_to_owner(self, redis_db):
        redis_db.upsert(content_hash="hc", documents=[_embedded("owned", "same")], user_id="alice")
        assert _queried_filter(redis_db) == "(@content_hash:{hc} @user_id:{alice})"

    def test_shared_upsert_dedup_scoped_to_shared(self, redis_db):
        redis_db.upsert(content_hash="hc", documents=[_embedded("shared", "same")], user_id=None)
        assert _queried_filter(redis_db) == "(@content_hash:{hc} @user_id:{__shared__})"


class TestDeleteScope:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to the caller's chunks."""

    def test_scoped_delete_restricts_to_owner(self, redis_db):
        redis_db.delete_by_content_id("cid1", user_id="alice")
        # Owner-only: no ``|__shared__`` alternation here, unlike a read scope.
        assert _queried_filter(redis_db) == "@content_id:{cid1} @user_id:{alice}"

    def test_unscoped_delete_spans_all_owners(self, redis_db):
        redis_db.delete_by_content_id("cid1", user_id=None)
        assert _queried_filter(redis_db) == "@content_id:{cid1}"


class TestUserIdValidation:
    """Reserved and structurally unsafe owner values are rejected up front."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # an owner tag no scope clause can match
            RedisDb.SHARED_OWNER_TAG,  # shared-bucket impersonation
            "alice*",  # wildcard matches other owners
            "alice?",  # wildcard matches other owners
            "alice{1}",  # brace can never be matched by a scope clause
            "a\x1fb",  # separator indexes one value as several tags
            "victim\x00attacker",  # NUL truncates at index time onto the victim's tag
            "x" * 4097,  # over the indexed TAG limit, truncates onto a shorter owner
            " alice",  # leading whitespace is trimmed by the index and collapses onto 'alice'
            "alice ",  # trailing whitespace collapses onto 'alice'
        ],
    )
    def test_rejects_unsafe_user_id(self, redis_db, bad):
        with pytest.raises(ValueError):
            redis_db._validate_user_id(bad)
        # The rejection is enforced on the write path, not just in the helper.
        with pytest.raises(ValueError):
            redis_db.insert(content_hash="h", documents=[_embedded("a", "x")], user_id=bad)
        assert not redis_db.index.load.called

    def test_none_is_allowed(self, redis_db):
        redis_db._validate_user_id(None)

    @pytest.mark.parametrize(
        "good",
        [
            "alice",
            "alice-1",
            "user_42",
            "alice@example.com",
            # OIDC subjects carry the TAG union character; the scope clause escapes it.
            "auth0|507f1f77bcf86cd799439011",
            "google-oauth2|103547991597142817347",
        ],
    )
    def test_accepts_legitimate_user_id(self, redis_db, good):
        redis_db._validate_user_id(good)
        redis_db.insert(content_hash="h", documents=[_embedded("a", "x")], user_id=good)
        assert redis_db.index.load.called

    @pytest.mark.parametrize(
        "owner",
        ["user\U0001f600x", "user–x", "user’x", "Петя", "café", "user x"],
    )
    def test_non_ascii_owner_is_not_over_escaped(self, redis_db, owner):
        """Over-escaping leaves a literal backslash in the query, so the owner cannot read their own chunks."""
        sent = str(redis_db._user_scope_filter(owner))
        assert sent == f"@user_id:{{{owner.replace(' ', chr(92) + ' ')}|__shared__}}"

    def test_oidc_subject_is_escaped_not_unioned(self, redis_db):
        """A '|' in the owner must stay a literal, not the TAG union operator, or the scope widens."""
        sent = str(redis_db._user_scope_filter("auth0|507f1f77bcf86cd799439011"))
        assert sent == "@user_id:{auth0\\|507f1f77bcf86cd799439011|__shared__}"

    @pytest.mark.asyncio
    async def test_async_insert_rejects_unsafe_user_id(self, redis_db):
        with pytest.raises(ValueError):
            await redis_db.async_insert(content_hash="h", documents=[_embedded("a", "x")], user_id="")
