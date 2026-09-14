"""Unit tests for the strict owner scope on knowledge-content deletes.

Reads are inclusive: a scoped caller sees their own rows plus the shared /
unowned ones. Deletes are strict: a scoped caller only removes rows they own, so
an admin-uploaded org-wide row survives ``user_id="alice"`` and is removed only
by the unscoped (admin) call.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb
from agno.db.mongo import MongoDb
from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite import SqliteDb

SHARED = "k_shared"  # admin-uploaded, org-wide: user_id is None
ALICE = "k_alice"
BOB = "k_bob"


@pytest.fixture(params=["sqlite", "in_memory", "json"])
def db(request, tmp_path):
    if request.param == "sqlite":
        return SqliteDb(db_file=str(tmp_path / "knowledge_isolation.db"))
    if request.param == "in_memory":
        return InMemoryDb()
    return JsonDb(db_path=str(tmp_path / "knowledge_isolation_json"))


def _make(db, id, user_id):
    db.upsert_knowledge_content(KnowledgeRow(id=id, name=id, description="content", user_id=user_id))


def seeded_ids(db):
    rows, _ = db.get_knowledge_contents()
    return {row.id for row in rows}


@pytest.fixture
def seeded(db):
    _make(db, SHARED, None)
    _make(db, ALICE, "alice")
    _make(db, BOB, "bob")
    return db


class TestScopedDeleteIsStrict:
    def test_shared_row_survives_scoped_delete(self, seeded):
        seeded.delete_knowledge_content(SHARED, user_id="alice")
        assert seeded.get_knowledge_content(SHARED) is not None

    def test_shared_row_deleted_by_admin(self, seeded):
        seeded.delete_knowledge_content(SHARED, user_id=None)
        assert seeded.get_knowledge_content(SHARED) is None

    def test_own_row_deleted(self, seeded):
        seeded.delete_knowledge_content(ALICE, user_id="alice")
        assert seeded.get_knowledge_content(ALICE) is None

    def test_other_users_row_survives(self, seeded):
        seeded.delete_knowledge_content(BOB, user_id="alice")
        assert seeded.get_knowledge_content(BOB) is not None

    def test_owned_row_deleted_by_admin(self, seeded):
        seeded.delete_knowledge_content(ALICE, user_id=None)
        assert seeded.get_knowledge_content(ALICE) is None

    def test_empty_string_is_a_real_owner(self, db):
        """``""`` scopes to itself; it is not a second spelling of "unscoped"."""
        _make(db, SHARED, None)
        _make(db, ALICE, "alice")
        _make(db, "k_empty", "")

        db.delete_knowledge_content(SHARED, user_id="")
        db.delete_knowledge_content(ALICE, user_id="")
        assert seeded_ids(db) == {SHARED, ALICE, "k_empty"}

        db.delete_knowledge_content("k_empty", user_id="")
        assert seeded_ids(db) == {SHARED, ALICE}

    def test_scoped_delete_leaves_everything_else_alone(self, seeded):
        seeded.delete_knowledge_content(ALICE, user_id="alice")

        rows, total = seeded.get_knowledge_contents()
        assert {row.id for row in rows} == {SHARED, BOB}
        assert total == 2


class TestReadsStayInclusive:
    def test_scoped_read_still_sees_shared_row(self, seeded):
        assert seeded.get_knowledge_content(SHARED, user_id="alice") is not None

    def test_scoped_listing_still_sees_shared_row(self, seeded):
        rows, total = seeded.get_knowledge_contents(user_id="alice")
        assert {row.id for row in rows} == {SHARED, ALICE}
        assert total == 2


class TestScopedUpsertIsStrict:
    """A scoped upsert must not overwrite a row it does not own: an upsert keys on ``id``
    alone, so a caller whose content id collides with another owner's row would otherwise
    replace it and take ownership."""

    def test_cannot_take_over_another_users_row(self, db):
        _make(db, ALICE, "alice")
        with pytest.raises(ValueError):
            _make(db, ALICE, "bob")
        assert db.get_knowledge_content(ALICE).user_id == "alice"

    def test_cannot_take_over_a_shared_row(self, db):
        _make(db, SHARED, None)
        with pytest.raises(ValueError):
            _make(db, SHARED, "alice")
        assert db.get_knowledge_content(SHARED).user_id is None

    def test_owner_and_admin_can_still_write(self, db):
        _make(db, ALICE, "alice")
        _make(db, ALICE, "alice")  # the owner updating their own row is allowed
        _make(db, SHARED, None)
        _make(db, SHARED, None)  # an unscoped (admin) write to a shared row is allowed
        assert db.get_knowledge_content(ALICE).user_id == "alice"
        assert db.get_knowledge_content(SHARED).user_id is None


# -- Postgres: SQLAlchemy statement predicate --


def _knowledge_table():
    """A minimal stand-in for the knowledge table the adapter would resolve."""
    return Table(
        "knowledge",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("user_id", String),
    )


def _captured_delete_sql(user_id):
    """Run the Postgres delete against mocks and return the SQL it issued."""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    db = PostgresDb(db_engine=engine, knowledge_table="knowledge")

    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    db.Session = Mock(return_value=session)

    with patch.object(db, "_get_table", return_value=_knowledge_table()):
        db.delete_knowledge_content(SHARED, user_id=user_id)

    stmt = session.execute.call_args[0][0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


class TestPostgresDeletePredicate:
    def test_scoped_delete_matches_owner_only(self):
        sql = _captured_delete_sql("alice")
        assert "knowledge.user_id = 'alice'" in sql
        # The inclusive OR-with-NULL clause would let alice delete shared rows
        assert "IS NULL" not in sql

    def test_unscoped_delete_has_no_owner_predicate(self):
        sql = _captured_delete_sql(None)
        assert "user_id" not in sql


# -- Mongo: filter document --


class TestMongoDeleteFilter:
    def _db(self):
        return MongoDb(db_url="mongodb://localhost:27017", db_name="test_db", knowledge_collection="knowledge")

    def test_scoped_delete_matches_owner_only(self):
        db = self._db()
        coll = MagicMock()
        with patch.object(db, "_get_collection", return_value=coll):
            db.delete_knowledge_content(SHARED, user_id="alice")
        # An $or with {"user_id": None} would match the shared row
        assert coll.delete_one.call_args[0][0] == {"id": SHARED, "user_id": "alice"}

    def test_unscoped_delete_matches_on_id_only(self):
        db = self._db()
        coll = MagicMock()
        with patch.object(db, "_get_collection", return_value=coll):
            db.delete_knowledge_content(SHARED, user_id=None)
        assert coll.delete_one.call_args[0][0] == {"id": SHARED}


# -- Redis: read-then-delete ownership check --


@pytest.fixture
def redis_db():
    # Fixture-scoped: at module level this would skip the embedded-backend cases too.
    fakeredis = pytest.importorskip("fakeredis")
    from agno.db.redis.redis import RedisDb

    db = RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True), db_prefix="agno")
    _make(db, SHARED, None)
    _make(db, ALICE, "alice")
    _make(db, BOB, "bob")
    return db


class TestRedisScopedDeleteIsStrict:
    def test_shared_row_survives_scoped_delete(self, redis_db):
        redis_db.delete_knowledge_content(SHARED, user_id="alice")
        assert redis_db.get_knowledge_content(SHARED) is not None

    def test_shared_row_deleted_by_admin(self, redis_db):
        redis_db.delete_knowledge_content(SHARED, user_id=None)
        assert redis_db.get_knowledge_content(SHARED) is None

    def test_own_row_deleted(self, redis_db):
        redis_db.delete_knowledge_content(ALICE, user_id="alice")
        assert redis_db.get_knowledge_content(ALICE) is None

    def test_owned_row_deleted_by_admin(self, redis_db):
        redis_db.delete_knowledge_content(ALICE, user_id=None)
        assert redis_db.get_knowledge_content(ALICE) is None

    def test_other_users_row_survives(self, redis_db):
        redis_db.delete_knowledge_content(BOB, user_id="alice")
        assert redis_db.get_knowledge_content(BOB) is not None

    def test_scoped_read_still_sees_shared_row(self, redis_db):
        assert redis_db.get_knowledge_content(SHARED, user_id="alice") is not None
