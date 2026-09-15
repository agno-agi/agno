"""search_learnings must raise on a database error, never return an empty
list -- the explicit contract on BaseDb.search_learnings (base.py). A broken
query must not be mistaken for an empty store: unlike most other read
methods here, this one is a deliberate exception to swallowing errors and
logging instead.

Mirrors the live-server-mirror convention used across tests/unit/db/*_postgres.py:
skips cleanly when no Oracle server is reachable.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.oracle import OracleDb

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
    suffix = uuid.uuid4().hex[:8]
    database = OracleDb(db_url=DB_URL, learnings_table=f"test_search_raises_{suffix}")
    yield database
    database.Session.remove()
    if database.table_exists(database.learnings_table_name):
        with database.db_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE {database.learnings_table_name} CASCADE CONSTRAINTS"))
    database.db_engine.dispose()


def test_search_learnings_on_populated_store_finds_nothing_returns_empty(db):
    """The unpopulated/no-match case is not an error: it returns []."""
    db.upsert_learning(id="l1", learning_type="user_profile", content={"summary": "hello world"}, user_id="alice")
    assert db.search_learnings(query="no-such-term-zzz") == []


def test_search_learnings_raises_on_a_broken_query_rather_than_returning_empty(db):
    """A genuine query failure (here: a bind-type mismatch on an existing,
    populated table) must propagate, not come back as an empty list -- the
    caller would otherwise have no way to distinguish "nothing matched" from
    "the query itself is broken".
    """
    db.upsert_learning(id="l1", learning_type="user_profile", content={"summary": "hello world"}, user_id="alice")

    with pytest.raises(Exception):
        db.search_learnings(query="alice", learning_type={"not": "a valid value"})  # type: ignore[arg-type]
