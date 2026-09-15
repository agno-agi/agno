"""OracleVector per-user isolation, against a live Oracle container.

Unlike the mock-based ``test_*_user_isolation.py`` files for backends with no
test image available, Oracle's empty-string-is-null folding (the highest-
stakes behavior this ticket calls out -- see OracleVector's own module
docstring) is a genuine database behavior a mocked session can't reproduce.
This file runs against a real server and skips cleanly when one isn't
reachable, matching the convention already established for the Oracle
storage adapter's own live-server test files (ADR 0009: no Oracle container
in public CI).
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.knowledge.document import Document
from agno.vectordb.oracle.oracle import OracleVector, _to_db_user_id

from .conftest import DeterministicEmbedder

DB_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from dual"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _oracle_server():
    if not _server_reachable():
        pytest.skip(f"Oracle server not reachable at {DB_URL}")


@pytest.fixture
def db(_oracle_server):
    table_name = f"test_iso_{uuid.uuid4().hex[:8]}"
    database = OracleVector(table_name=table_name, db_url=DB_URL, embedder=DeterministicEmbedder())
    database.create()
    yield database
    database.drop()


def _raw_row(db: OracleVector, doc_id: str):
    with db.Session() as sess:
        return sess.execute(text(f"SELECT user_id FROM {db.table_name} WHERE id = :id"), {"id": doc_id}).fetchone()


class TestWriteStampsOwner:
    """The owner is stored as a first-class ``user_id`` column."""

    def test_explicit_user_id_stamped(self, db):
        doc = Document(name="alice-salary", content="Alice's salary is 180k.")
        db.insert(content_hash="h1", documents=[doc], user_id="alice")
        record_id = db._scoped_record_id(__import__("hashlib").md5(doc.content.encode()).hexdigest(), "h1", "alice")
        row = _raw_row(db, record_id)
        assert row is not None and row.user_id == "alice"

    def test_none_user_id_stored_as_null(self, db):
        doc = Document(name="company-holidays", content="The office is closed Jan 1.")
        db.insert(content_hash="h2", documents=[doc], user_id=None)
        record_id = db._scoped_record_id(__import__("hashlib").md5(doc.content.encode()).hexdigest(), "h2", None)
        row = _raw_row(db, record_id)
        assert row is not None and row.user_id is None


class TestEmptyStringOwnerSentinel:
    """The empty-string-is-null problem: the highest-stakes case this ticket calls
    out. Oracle folds "" to NULL on write, and NULL is the genuine shared bucket --
    an unowned owner arriving from the application must become the sentinel
    (verified directly against the raw stored column) or it silently leaks into
    the shared bucket, with no error raised.
    """

    def test_empty_string_owner_is_not_stored_as_null(self, db):
        doc = Document(name="empty-owner-doc", content="Content with an empty owner string.")
        db.insert(content_hash="h3", documents=[doc], user_id="")
        record_id = db._scoped_record_id(__import__("hashlib").md5(doc.content.encode()).hexdigest(), "h3", "")
        row = _raw_row(db, record_id)
        assert row is not None
        assert row.user_id is not None, "an empty-string owner must never be stored as NULL (the shared bucket)"
        assert row.user_id == _to_db_user_id("")

    def test_empty_string_owner_does_not_leak_into_shared_search(self, db):
        empty_doc = Document(name="empty-owner-doc", content="Secret content with an empty owner string.")
        shared_doc = Document(name="shared-doc", content="Genuinely shared content.")
        db.insert(content_hash="h4", documents=[empty_doc], user_id="")
        db.insert(content_hash="h5", documents=[shared_doc], user_id=None)

        results = db.search("content", limit=10, user_id="someone-else")
        names = {r.name for r in results}
        assert "shared-doc" in names
        assert "empty-owner-doc" not in names, "an empty-string owner's row leaked into the shared (NULL) bucket"

    def test_empty_string_owner_sees_its_own_content(self, db):
        doc = Document(name="empty-owner-doc", content="Content only the empty-string owner should see again.")
        db.insert(content_hash="h6", documents=[doc], user_id="")
        results = db.search("Content only the empty-string owner", limit=10, user_id="")
        assert any(r.name == "empty-owner-doc" for r in results)


class TestOwnerFoldedId:
    """Two owners uploading the same content get distinct row ids."""

    def test_identical_content_two_owners_get_distinct_ids(self, db):
        content = "The merger closes in Q3."
        alice_id = db._scoped_record_id(__import__("hashlib").md5(content.encode()).hexdigest(), "hX", "alice")
        bob_id = db._scoped_record_id(__import__("hashlib").md5(content.encode()).hexdigest(), "hX", "bob")
        assert alice_id != bob_id

    def test_partitioned_inputs_do_not_collide(self, db):
        """A base id with a trailing fragment must not collide with another whose
        owner happens to supply that fragment -- the two-stage digest folds
        base_id+content_hash first, then owner, rather than joining raw strings.
        """
        id_a = db._scoped_record_id("doc_1", "hY", "alice")
        id_b = db._scoped_record_id("doc", "hY", "1_alice")
        assert id_a != id_b


class TestSearchScope:
    """A scoped search returns own rows plus shared, never another owner's."""

    def test_named_owner_sees_own_and_shared_not_others(self, db):
        db.insert(
            content_hash="ha", documents=[Document(name="alice-doc", content="Alice private note.")], user_id="alice"
        )
        db.insert(content_hash="hb", documents=[Document(name="bob-doc", content="Bob private note.")], user_id="bob")
        db.insert(content_hash="hs", documents=[Document(name="shared-doc", content="Shared note.")], user_id=None)

        alice_results = {r.name for r in db.search("note", limit=10, user_id="alice")}
        assert "alice-doc" in alice_results
        assert "shared-doc" in alice_results
        assert "bob-doc" not in alice_results

    def test_owner_scoping_applies_to_keyword_and_hybrid_too(self, db):
        """Ticket 18: owner scoping is applied before filters on all three
        search paths, not just vector_search.
        """
        db.insert(
            content_hash="ka",
            documents=[Document(name="alice-secret", content="Alice keeps a secret furry pet journal.")],
            user_id="alice",
        )
        db.insert(
            content_hash="kb",
            documents=[Document(name="bob-journal", content="Bob keeps a furry pet journal too.")],
            user_id="bob",
        )
        db.optimize()

        bob_keyword_names = {r.name for r in db.keyword_search("furry pet journal", limit=10, user_id="bob")}
        assert "alice-secret" not in bob_keyword_names
        assert "bob-journal" in bob_keyword_names

        bob_hybrid_names = {r.name for r in db.hybrid_search("furry pet journal", limit=10, user_id="bob")}
        assert "alice-secret" not in bob_hybrid_names
        assert "bob-journal" in bob_hybrid_names


class TestUpsertDedupScope:
    """Upsert dedup keys on content_hash scoped by owner: it clears only the
    writing owner's own bucket, never another owner's or the shared bucket.
    """

    def test_dedup_is_scoped_to_writing_owner(self, db):
        db.insert(content_hash="hd", documents=[Document(name="d1", content="first version")], user_id="carol")
        db.upsert(content_hash="hd", documents=[Document(name="d1", content="second version")], user_id="carol")
        results = db.search("version", limit=10, user_id="carol")
        matching = [r for r in results if r.name == "d1"]
        assert len(matching) == 1
        assert matching[0].content == "second version"

    def test_shared_upsert_dedup_does_not_touch_owned_rows(self, db):
        db.insert(content_hash="he", documents=[Document(name="owned", content="owned content")], user_id="dave")
        db.insert(content_hash="he", documents=[Document(name="shared", content="shared content v1")], user_id=None)
        db.upsert(content_hash="he", documents=[Document(name="shared", content="shared content v2")], user_id=None)
        owned_still_there = db.search("owned content", limit=10, user_id="dave")
        assert any(r.name == "owned" for r in owned_still_there)


class TestDeleteScope:
    """``delete_by_content_id``/``_delete_by_content_hash`` with a ``user_id``
    restrict the delete to that owner's rows.
    """

    def test_scoped_delete_by_content_hash_restricts_to_owner(self, db):
        db.insert(content_hash="hf", documents=[Document(name="erin-doc", content="erin content")], user_id="erin")
        deleted = db._delete_by_content_hash("hf", user_id="frank")
        assert deleted is False
        still_there = db.search("erin content", limit=10, user_id="erin")
        assert any(r.name == "erin-doc" for r in still_there)

        deleted_correctly = db._delete_by_content_hash("hf", user_id="erin")
        assert deleted_correctly is True
