import os
import uuid

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType

redisvl = pytest.importorskip("redisvl")

from agno.vectordb.redis.redisdb import RedisDB  # noqa: E402

REDIS_URL = os.environ.get("REDIS_ISOLATION_URL", "redis://localhost:6380")


def _server_has_search() -> bool:
    """The isolation primitives need the RediSearch module; a plain redis
    server can't create the index, so skip rather than fail spuriously."""
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2)
        modules = client.module_list()
        names = {m.get(b"name", m.get("name")) for m in modules}
        names = {n.decode() if isinstance(n, bytes) else n for n in names}
        return "search" in names
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_has_search(),
    reason=f"redis-stack with RediSearch not reachable at {REDIS_URL}",
)


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key. The content steers
    the vector so distinct documents land in distinct buckets — all the
    isolation tests need, and it gives us a real async surface too."""

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


def _embedded(name: str, content: str, content_id: str = None) -> Document:
    """A Document with a precomputed deterministic embedding so direct
    ``insert`` calls work without an embedder round-trip."""
    doc = Document(name=name, content=content)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


def _make_db(search_type: SearchType = SearchType.vector) -> RedisDB:
    """A fresh RedisDB on a unique index so parallel runs don't collide."""
    index_name = f"iso_test_{uuid.uuid4().hex[:10]}"
    db = RedisDB(
        index_name=index_name,
        redis_url=REDIS_URL,
        embedder=_DeterministicEmbedder(),
        search_type=search_type,
    )
    db.create()
    return db


@pytest.fixture(params=[SearchType.vector, SearchType.keyword, SearchType.hybrid])
def db(request):
    """A fresh isolated index per test, parametrized over every search mode so
    isolation is asserted across vector, keyword AND hybrid."""
    database = _make_db(request.param)
    yield database
    try:
        database.drop()
    except Exception:
        pass


@pytest.fixture
def vector_db():
    """A single-mode (vector) index for tests that don't need to sweep modes."""
    database = _make_db(SearchType.vector)
    yield database
    try:
        database.drop()
    except Exception:
        pass


def _alice_docs():
    return [_embedded("alice-salary", "Alice secret salary is 180k.")]


def _bob_docs():
    return [_embedded("bob-salary", "Bob secret salary is 215k.")]


def _shared_docs():
    return [_embedded("company-holidays", "The office secret is closed Jan 1.")]


def _owners(db: RedisDB):
    """Read the raw ``user_id`` tag off every stored hash (absent -> None)."""
    from redisvl.query import FilterQuery
    from redisvl.redis.utils import convert_bytes

    q = FilterQuery(
        filter_expression=None,
        return_fields=["id", RedisDB.USER_ID_FIELD],
        num_results=1000,
    )
    rows = convert_bytes(db.index.query(q))
    return sorted((r.get(RedisDB.USER_ID_FIELD) for r in rows), key=lambda x: (x is None, x))


def _count(db: RedisDB) -> int:
    from redisvl.query import FilterQuery

    q = FilterQuery(filter_expression=None, return_fields=["id"], num_results=1000)
    return len(db.index.query(q))


class TestWriteStampsOwner:
    """``user_id`` is a top-level TAG field, not nested in ``meta_data``.
    Shared chunks OMIT the field so ``ismissing`` can surface them."""

    def test_user_id_field_constant(self):
        # Storage compatibility marker — changing it orphans the scope on
        # every previously persisted row.
        assert RedisDB.USER_ID_FIELD == "user_id"

    def test_explicit_user_id_persisted(self, vector_db):
        vector_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        assert _owners(vector_db) == ["alice"]

    def test_none_user_id_omits_field(self, vector_db):
        """Shared chunks store no ``user_id`` field at all — an empty string
        would NOT be treated as missing by RediSearch."""
        vector_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        assert _owners(vector_db) == [None]

    def test_user_id_omitted_defaults_to_shared(self, vector_db):
        vector_db.insert(content_hash="h1", documents=_shared_docs())
        assert _owners(vector_db) == [None]

    def test_caller_meta_data_cannot_set_owner(self, vector_db):
        """A caller's own ``meta_data['user_id']`` must not become the owner
        tag — the owner is stamped after the meta_data merge."""
        doc = _embedded("md", "secret content")
        doc.meta_data = {"user_id": "attacker"}
        vector_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        assert _owners(vector_db) == ["alice"]


class TestUserScopeFilter:
    """The scope-filter builder is small enough to unit-test directly."""

    def test_none_returns_no_filter(self, vector_db):
        assert vector_db._user_scope_filter(None) is None

    def test_scope_is_own_or_missing(self, vector_db):
        f = vector_db._user_scope_filter("alice")
        rendered = str(f)
        assert "@user_id:{alice}" in rendered
        assert "ismissing(@user_id)" in rendered
        # Parenthesized so it can splice before the KNN clause in vector/hybrid.
        assert rendered.startswith("(") and rendered.endswith(")")


class TestSearchIsolationContract:
    """The load-bearing test, swept over vector / keyword / hybrid: alice's
    search returns her chunks plus shared chunks, but never bob's."""

    @pytest.fixture
    def populated(self, db):
        db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("secret salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        results = populated.search("secret salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        for d in results:
            assert "Bob secret salary" not in d.content

    def test_bob_never_sees_alice(self, populated):
        names = {d.name for d in populated.search("secret salary", limit=10, user_id="bob")}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated):
        names = {d.name for d in populated.search("secret salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestAsyncSearchIsolation:
    """Async variants must isolate identically across all three modes."""

    async def _populate_async(self, db):
        await db.async_create()
        await db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

    async def test_async_alice_isolated(self, db):
        await self._populate_async(db)
        names = {d.name for d in await db.async_search("secret salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_admin_sees_all(self, db):
        await self._populate_async(db)
        names = {d.name for d in await db.async_search("secret salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope to the
    caller's chunks and never touch the shared bucket."""

    @pytest.fixture
    def populated(self, vector_db):
        vector_db.insert(
            content_hash="ha", documents=[_embedded("alice-doc", "alice secret", "doc-1")], user_id="alice"
        )
        vector_db.insert(content_hash="hb", documents=[_embedded("bob-doc", "bob secret", "doc-1")], user_id="bob")
        vector_db.insert(content_hash="hs", documents=[_embedded("shared-doc", "shared secret", "doc-1")], user_id=None)
        return vector_db

    def test_scoped_delete_removes_only_caller(self, populated):
        populated.delete_by_content_id("doc-1", user_id="bob")
        # ``_owners`` sorts None last.
        assert _owners(populated) == ["alice", None]

    def test_scoped_delete_never_touches_shared(self, populated):
        """A scoped caller deleting their own content must leave the shared
        (None-owned) chunk alone — wiping org content is a breach."""
        populated.delete_by_content_id("doc-1", user_id="alice")
        assert _owners(populated) == ["bob", None]

    def test_scoped_delete_no_op_when_not_owner(self, populated):
        populated.delete_by_content_id("doc-1", user_id="carol")
        assert _count(populated) == 3

    def test_unscoped_delete_wipes_all_owners(self, populated):
        populated.delete_by_content_id("doc-1", user_id=None)
        assert _count(populated) == 0


class TestClobberPrevention:
    """Two users uploading identical content under the SAME content_hash must
    coexist; a same-user re-upsert must replace in place."""

    def test_two_users_same_content_and_hash_coexist(self, vector_db):
        vector_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice")
        vector_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob")
        assert _owners(vector_db) == ["alice", "bob"]

    def test_clobbered_rows_stay_isolated_on_search(self, vector_db):
        vector_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice")
        vector_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob")
        alice = {d.name for d in vector_db.search("secret", limit=10, user_id="alice")}
        bob = {d.name for d in vector_db.search("secret", limit=10, user_id="bob")}
        assert alice == {"secret"}
        assert bob == {"secret"}
        assert _count(vector_db) == 2

    def test_shared_bucket_keeps_legacy_id(self, vector_db):
        """``user_id=None`` keeps the unscoped id so previously persisted shared
        rows stay byte-identical and addressable."""
        assert vector_db._scoped_doc_id("base", None) == "base"
        assert vector_db._scoped_doc_id("base", "alice") != "base"


class TestUpsertDedupeIsolation:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner."""

    def test_same_user_reupsert_replaces(self, vector_db):
        vector_db.upsert(content_hash="H", documents=[_embedded("d", "content v1")], user_id="alice")
        vector_db.upsert(content_hash="H", documents=[_embedded("d", "content v2")], user_id="alice")
        assert _count(vector_db) == 1

    def test_scoped_dedupe_does_not_touch_other_owner(self, vector_db):
        vector_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        vector_db.upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        # Alice re-upserts under the shared hash; bob's chunk must survive.
        vector_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        assert _owners(vector_db) == ["alice", "bob"]
        assert _count(vector_db) == 2

    def test_shared_upsert_does_not_wipe_scoped(self, vector_db):
        """An admin re-upserting shared content under a hash must not delete a
        scoped user's chunk carrying the same hash."""
        vector_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        vector_db.upsert(content_hash="SH", documents=[_embedded("sd", "shared v1")], user_id=None)
        vector_db.upsert(content_hash="SH", documents=[_embedded("sd", "shared v2")], user_id=None)
        # ``_owners`` sorts None last.
        assert _owners(vector_db) == ["alice", None]


class TestAsyncUpsertDedupe:
    """Async upsert must match sync dedupe behaviour."""

    async def test_async_reupsert_replaces(self, vector_db):
        await vector_db.async_create()
        await vector_db.async_upsert(content_hash="H", documents=[_embedded("d", "v1")], user_id="alice")
        await vector_db.async_upsert(content_hash="H", documents=[_embedded("d", "v2")], user_id="alice")
        assert _count(vector_db) == 1

    async def test_async_scoped_dedupe_keeps_other_owner(self, vector_db):
        await vector_db.async_create()
        await vector_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        await vector_db.async_upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        await vector_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        assert _owners(vector_db) == ["alice", "bob"]
        assert _count(vector_db) == 2


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` must not let a caller reassign the owner tag."""

    @pytest.fixture
    def owned(self, vector_db):
        vector_db.insert(content_hash="hm", documents=[_embedded("md", "metadata content", "cid-1")], user_id="alice")
        return vector_db

    def test_caller_cannot_reassign_owner(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob", "category": "x"})
        assert _owners(owned) == ["alice"]

    def test_legitimate_metadata_still_applied(self, owned):
        owned.update_metadata("cid-1", {"category": "x", "user_id": "bob"})
        names = {d.name for d in owned.search("metadata", limit=10, user_id="alice")}
        assert "md" in names
        # Bob must still not see it.
        assert "md" not in {d.name for d in owned.search("metadata", limit=10, user_id="bob")}


class TestPipeInUserIdOwnerSeesOwnChunks:
    """An OIDC/Auth0 ``user_id`` is ``provider|sub`` (e.g. ``auth0|abc123``).
    RedisVL does not escape the ``|`` it emits, so RediSearch parses the owner
    tag as a tag-union and the owner sees ZERO of their own chunks. The owner
    tag must escape the ``|`` so the value matches as a single literal."""

    def test_pipe_user_id_sees_own_and_shared_never_bob(self, vector_db):
        owner = "auth0|abc123"
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id=owner)
        vector_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        vector_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        names = {d.name for d in vector_db.search("secret", limit=10, user_id=owner)}
        # Without the ``|`` escape the owner's own chunk is dropped (tag-union
        # parse), leaving only the shared chunk.
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_pipe_user_id_isolated_every_mode(self, db):
        """The ``|`` escape must hold on the async surface across vector,
        keyword AND hybrid — the dedupe/delete escape is moot if a search mode
        leaks."""
        owner = "auth0|abc123"
        await db.async_create()
        await db.async_insert(content_hash="ha", documents=_alice_docs(), user_id=owner)
        await db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        await db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        names = {d.name for d in await db.async_search("secret", limit=10, user_id=owner)}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names


class TestCommaInUserIdDoesNotSplitTag:
    """A RediSearch TAG field splits its stored value on a separator (default
    ``,``). With the default a ``user_id`` like ``a,b,c`` indexes THREE tags, so
    the owner can't match their own row (self-starve) AND — far worse — an id
    crafted as a victim's comma-delimited subsequence LEAKS across tenants. The
    owner field pins a non-default separator so the id is one atomic tag."""

    def test_separator_is_not_the_default_comma(self, vector_db):
        # Storage marker: a comma separator re-introduces the split-tag leak.
        assert vector_db.USER_ID_SEPARATOR != ","

    def test_comma_user_id_sees_own_and_shared(self, vector_db):
        owner = "a,b,c"
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id=owner)
        vector_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        names = {d.name for d in vector_db.search("secret", limit=10, user_id=owner)}
        # With the default comma separator the owner saw only the shared chunk.
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_comma_subsequence_does_not_leak_across_tenants(self, vector_db):
        """Bob's id is ``alice,bob``; under a comma separator it indexes the tag
        ``alice``, so Alice's scoped search would surface Bob's chunk. The owner
        must be a single tag so Alice (id ``alice``) never matches Bob's row."""
        vector_db.insert(content_hash="hb", documents=_bob_docs(), user_id="alice,bob")
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        names = {d.name for d in vector_db.search("secret salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names
