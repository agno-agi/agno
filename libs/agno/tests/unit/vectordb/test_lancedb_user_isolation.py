import os
import shutil
from typing import Any, Dict, List, Tuple

import pytest

from agno.knowledge.document import Document
from agno.vectordb.lancedb import LanceDb

TEST_TABLE = "test_isolation_table"
TEST_PATH = "tmp/test_lancedb_isolation"


@pytest.fixture
def lance_db(mock_embedder):
    """A fresh LanceDb per test — the schema change for ``user_id`` is in the
    base schema and would conflict with any cached table from another test."""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = LanceDb(uri=TEST_PATH, table_name=TEST_TABLE, embedder=mock_embedder)
    db.create()
    yield db

    try:
        db.drop()
    except Exception:
        pass
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


class TestSchemaHasUserIdColumn:
    """Pin the schema. If somebody removes the column the isolation tests
    below would still pass (everything goes to NULL = looks shared)
    misleadingly; this test fails loudly at the schema level."""

    def test_user_id_column_exists_on_table(self, lance_db):
        column_names = lance_db.table.schema.names
        assert lance_db.USER_ID_COL in column_names

    def test_user_id_column_is_nullable(self, lance_db):
        field = lance_db.table.schema.field(lance_db.USER_ID_COL)
        assert field.nullable is True

    def test_user_id_col_constant_is_user_id(self):
        # If this changes, every persisted row's column would silently stop
        # being read by retrieval. Pin it.
        assert LanceDb.USER_ID_COL == "user_id"


class TestInsertPopulatesUserIdColumn:
    """The owner from the explicit ``user_id=`` kwarg lands in the column.
    Not in the JSON payload — that's the whole point of the refactor."""

    def test_explicit_user_id_persisted_in_column(self, lance_db):
        lance_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] == "alice"

    def test_none_user_id_persisted_as_null(self, lance_db):
        """A shared chunk has ``NULL`` in the column. Both isolation
        predicates (yours plus NULL) match this row."""
        lance_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] is None

    def test_user_id_omitted_defaults_to_null(self, lance_db):
        """Backwards-compatible: callers that never pass ``user_id`` get
        NULL (shared) — they're effectively opting out of isolation."""
        lance_db.insert(content_hash="h1", documents=_shared_docs())

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert rows[0][lance_db.USER_ID_COL] is None


class TestSearchIsolationContract:
    """alice's search returns her chunks plus shared chunks, but never bob's."""

    @pytest.fixture
    def populated_db(self, lance_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        lance_db.insert(content_hash="alice-doc", documents=_alice_docs(), user_id="alice")
        lance_db.insert(content_hash="bob-doc", documents=_bob_docs(), user_id="bob")
        lance_db.insert(content_hash="shared-doc", documents=_shared_docs(), user_id=None)
        return lance_db

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


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the
    delete to the caller's bucket — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    LanceDB scopes via the ``user_id`` column (``WHERE user_id = X``
    in ``.where()`` before scanning payloads).
    """

    @pytest.fixture
    def populated_db(self, lance_db):
        """Two users own chunks under the SAME content_id 'doc-1'. This
        is the realistic adversarial scenario — Bob guesses the id and
        tries to delete it. Without ``user_id`` scoping he'd wipe both."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        lance_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        lance_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return lance_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob asks to delete 'doc-1' under his own scope — alice's
        chunks must remain."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        rows = populated_db.table.search().select([populated_db.USER_ID_COL]).to_list()
        owners = sorted(r[populated_db.USER_ID_COL] for r in rows)
        assert owners == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        rows = populated_db.table.search().select([populated_db.USER_ID_COL]).to_list()
        owners = sorted(r[populated_db.USER_ID_COL] for r in rows)
        assert owners == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners.
        Pin it so we notice if the default semantics change."""
        populated_db.delete_by_content_id("doc-1", user_id=None)

        assert populated_db.table.count_rows() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, populated_db):
        """Carol has no chunks. Her scoped delete of doc-1 does nothing."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")

        assert populated_db.table.count_rows() == 2


class TestWhereClauseHelper:
    """The clause builder is small enough to unit-test directly. We can
    catch escaping bugs and shared-NULL semantics without spinning up a DB."""

    def test_none_returns_no_clause(self, lance_db):
        assert lance_db._user_scope_where_clause(None) is None

    def test_simple_alice_clause(self, lance_db):
        # Must match the caller's id OR the shared (NULL) bucket — both.
        clause = lance_db._user_scope_where_clause("alice")
        assert "user_id = 'alice'" in clause
        assert "user_id IS NULL" in clause
        assert " OR " in clause

    def test_single_quote_in_user_id_is_escaped(self, lance_db):
        """SQL injection guard. A user_id like ``o'reilly`` must not break
        the predicate or open a query-injection hole."""
        clause = lance_db._user_scope_where_clause("o'reilly")
        # Doubled single-quote — standard SQL escaping.
        assert "user_id = 'o''reilly'" in clause


class _ContentAwareEmbedder:
    """Deterministic embedder whose vector depends on the text. The shared
    ``mock_embedder`` returns one fixed vector for everything, which is fine
    for "who can see what" but useless for the prefilter test: with identical
    vectors there's no ANN ranking to subvert. Here strong/weak phrases map
    to distinct vectors so we can build a top-K cliff and prove the scope
    predicate runs BEFORE the ANN selection (``prefilter=True``)."""

    dimensions = 8
    enable_batch = False

    def _vec(self, text: str) -> List[float]:
        t = text.lower()
        if "strong-match" in t:
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if "weak-match" in t:
            return [0.9, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        h = (abs(hash(t)) % 1000) / 1000.0
        return [0.0, 0.0, 0.0, h, 1.0 - h, 0.0, 0.0, 0.0]

    def get_embedding(self, text: str) -> List[float]:
        return self._vec(text)

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Dict[str, Any]]:
        return self._vec(text), {"prompt_tokens": 1, "total_tokens": 1}

    async def async_get_embedding(self, text: str) -> List[float]:
        return self._vec(text)


@pytest.fixture
def content_aware_db():
    """Fresh LanceDb backed by the content-aware embedder."""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = LanceDb(uri=TEST_PATH, table_name=TEST_TABLE, embedder=_ContentAwareEmbedder())
    db.create()
    yield db

    try:
        db.drop()
    except Exception:
        pass
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


class TestPrefilterRunsBeforeAnn:
    """The scope predicate must run BEFORE the ANN top-K, not after. If it
    post-filtered, flooding the index with strongly-matching bob rows would
    push alice's one weak row out of the global top-K and she'd get nothing
    — the exact silent-truncation bug column isolation was meant to kill."""

    def test_alice_weak_row_survives_bob_flood(self, content_aware_db):
        for i in range(20):
            content_aware_db.insert(
                content_hash=f"bob-{i}",
                documents=[Document(name=f"bob-{i}", content="strong-match content")],
                user_id="bob",
            )
        content_aware_db.insert(
            content_hash="alice-weak",
            documents=[Document(name="alice-weak", content="weak-match content")],
            user_id="alice",
        )

        # Small limit + 20 strong bob rows: a post-filter would return empty.
        results = content_aware_db.search(query="strong-match", limit=3, user_id="alice")
        names = {d.name for d in results}
        assert "alice-weak" in names, "Prefilter regressed: alice's row lost behind bob's flood"
        assert not any(n.startswith("bob-") for n in names), "Isolation broken: bob's rows leaked"


class TestCrossUserClobber:
    """The vector DB is a PUBLIC API. Two callers may push the SAME content
    (hence the same ``content_hash``) under different ``user_id``s. Their
    rows must coexist and stay isolated — the row id folds in the owner so
    they never collide, and upsert dedupe is scoped to the owner."""

    def test_same_content_hash_two_users_coexist(self, lance_db):
        same = "shared-content-hash"
        lance_db.insert(same, [Document(name="alice-c", content="secret")], user_id="alice")
        lance_db.insert(same, [Document(name="bob-c", content="secret")], user_id="bob")

        assert lance_db.table.count_rows() == 2, "Cross-user clobber: one row overwrote the other"

        owners = sorted(
            r[lance_db.USER_ID_COL] for r in lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        )
        assert owners == ["alice", "bob"]

    def test_upsert_same_hash_does_not_wipe_other_user(self, lance_db):
        same = "shared-content-hash"
        lance_db.upsert(same, [Document(name="alice-c", content="alice text")], user_id="alice")
        lance_db.upsert(same, [Document(name="bob-c", content="bob text")], user_id="bob")
        # alice re-upserts the same hash — bob's row must remain.
        lance_db.upsert(same, [Document(name="alice-c2", content="alice text v2")], user_id="alice")

        assert lance_db.table.count_rows() == 2, "Scoped dedupe leaked across users"
        names = {d.name for d in lance_db.search(query="text", limit=10, user_id=None)}
        assert "alice-c2" in names
        assert "alice-c" not in names, "Same-user re-upsert should replace, not duplicate"
        assert "bob-c" in names, "Cross-user upsert dedupe wiped bob's row"

    def test_same_user_reupsert_replaces(self, lance_db):
        same = "h-1"
        lance_db.upsert(same, [Document(name="v1", content="version one")], user_id="alice")
        lance_db.upsert(same, [Document(name="v2", content="version two")], user_id="alice")

        assert lance_db.table.count_rows() == 1, "Same-user re-upsert duplicated instead of replacing"
        names = {d.name for d in lance_db.search(query="version", limit=10, user_id="alice")}
        assert names == {"v2"}

    def test_shared_upsert_does_not_wipe_scoped_owner(self, lance_db):
        """A shared/admin re-ingest (``user_id=None``) under a content_hash that a
        scoped owner already uses must dedupe only the NULL-owned bucket. The
        None upsert used to delete ACROSS all owners, wiping alice's row."""
        same = "shared-content-hash"
        lance_db.insert(same, [Document(name="alice-c", content="alice owned")], user_id="alice")
        lance_db.upsert(same, [Document(name="shared-c", content="shared text")], user_id=None)

        assert lance_db.table.count_rows() == 2, "Shared upsert wiped the scoped owner's row"
        owners = {r[lance_db.USER_ID_COL] for r in lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()}
        assert owners == {None, "alice"}, "Shared (None) upsert dedupe leaked into the scoped owner"
        # Alice still sees her own row...
        alice_names = {d.name for d in lance_db.search(query="anything", limit=10, user_id="alice")}
        assert "alice-c" in alice_names
        # ...and admin sees both.
        admin_names = {d.name for d in lance_db.search(query="anything", limit=10, user_id=None)}
        assert {"alice-c", "shared-c"} <= admin_names
class TestSqlInjectionThroughUserId:
    """A malicious ``user_id`` must not break out of the quoted predicate.
    The classic ``x' OR '1'='1`` payload must leak nothing and must not
    widen a scoped delete."""

    def test_injection_user_id_leaks_nothing(self, lance_db):
        lance_db.insert("h-secret", [Document(name="secret", content="top secret salary")], user_id="real-owner")
        lance_db.insert("h-shared", [Document(name="pub", content="public note")], user_id=None)

        results = lance_db.search(query="salary", limit=10, user_id="x' OR '1'='1")
        names = {d.name for d in results}
        assert "secret" not in names, "SQL injection leaked another user's chunk"
        # The injected id owns nothing, so only the shared (NULL) bucket shows.
        assert names <= {"pub"}

    def test_injection_user_id_does_not_widen_delete(self, lance_db):
        lance_db.insert("h-secret", [Document(name="secret", content="x", content_id="c-1")], user_id="real-owner")

        lance_db.delete_by_content_id("c-1", user_id="x' OR '1'='1")
        owners = [r[lance_db.USER_ID_COL] for r in lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()]
        assert "real-owner" in owners, "SQL injection through user_id widened a scoped delete"


class TestAsyncIsolation:
    """Async insert/upsert/search must enforce the same contract as sync —
    they delegate to the sync path, but pin it so a future async rewrite
    can't silently drop isolation."""

    async def test_async_insert_and_search_isolated(self, lance_db):
        await lance_db.async_insert("h-a", [Document(name="alice-a", content="alice salary")], user_id="alice")
        await lance_db.async_insert("h-b", [Document(name="bob-a", content="bob salary")], user_id="bob")
        a = {d.name for d in await lance_db.async_search(query="salary", limit=10, user_id="alice")}
        b = {d.name for d in await lance_db.async_search(query="salary", limit=10, user_id="bob")}
        assert "alice-a" in a and "bob-a" not in a
        assert "bob-a" in b and "alice-a" not in b

    async def test_async_upsert_clobber_isolated(self, lance_db):
        same = "async-same-hash"
        await lance_db.async_upsert(same, [Document(name="ca", content="alice")], user_id="alice")
        await lance_db.async_upsert(same, [Document(name="cb", content="bob")], user_id="bob")
        # alice re-upserts — bob untouched, alice replaced.
        await lance_db.async_upsert(same, [Document(name="ca2", content="alice v2")], user_id="alice")
        assert lance_db.table.count_rows() == 2
        owners = sorted(
            r[lance_db.USER_ID_COL] for r in lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        )
        assert owners == ["alice", "bob"]
