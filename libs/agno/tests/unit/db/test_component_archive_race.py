"""The "not archived" precondition rides the write itself (B13).

set_current_version and upsert_component used to read ``deleted_at IS NULL``
and then write without re-asserting it, so an archive committing between the
pre-read and the UPDATE was overtaken: the pointer (or a field write) landed
on an archived - immutable - row.

Each race here is deterministic, not probabilistic: a sqlalchemy event hook
pauses the writer thread AFTER its pre-reads, right before its UPDATE, while
the archive commits on a second connection. Exactly one winner: the archive.
The writer must observe the archived row (return False / raise
ComponentArchivedError) and the archived row must keep its pre-archive state.

SQLite runs unconditionally; the Postgres mirror runs against the live
pgvector container (localhost:5532) and skips when it is unreachable.
"""

import threading
import uuid

import pytest
from sqlalchemy import event

from agno.db.base import ComponentArchivedError, ComponentType
from agno.db.sqlite import SqliteDb

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _mk_component(db, cid):
    db.create_component_with_config(
        component_id=cid,
        component_type=ComponentType.AGENT,
        name=cid,
        config={"name": cid, "v": 1},
        stage="published",
    )
    db.upsert_config(cid, config={"name": cid, "v": 2}, stage="draft")
    db.upsert_config(cid, version=2, stage="published")  # current = 2
    return cid


class _ArchiveBetweenReadAndWrite:
    """Pause the writer thread's first UPDATE until an archive has committed.

    The hook arms once: the writer's pre-reads run, its UPDATE is held at the
    cursor, the main thread archives on a separate connection, then the UPDATE
    proceeds - the exact interleave the check-then-write bug loses.
    """

    def __init__(self, engine):
        self.engine = engine
        self.update_reached = threading.Event()
        self.archive_committed = threading.Event()
        self._armed = True

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        if self._armed and statement.lstrip().upper().startswith("UPDATE"):
            self._armed = False
            self.update_reached.set()
            assert self.archive_committed.wait(timeout=15), "archive never committed"

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc):
        # The archive thread finished and the hook disarmed itself; removal is
        # deferred to here so no dispatch iterates a mutating listener deque.
        event.remove(self.engine, "before_cursor_execute", self._hook)
        return False


def _run_race(writer_db, archiver_db, cid, writer_fn):
    """Two-thread barrier: writer pauses before its UPDATE, archive wins first."""
    outcome = {}

    def writer():
        try:
            outcome["result"] = writer_fn()
        except Exception as e:
            outcome["error"] = e

    with _ArchiveBetweenReadAndWrite(writer_db.db_engine) as race:
        t = threading.Thread(target=writer)
        t.start()
        assert race.update_reached.wait(timeout=15), "writer never reached its UPDATE"
        assert archiver_db.delete_component(cid) is True  # the archive commits first
        race.archive_committed.set()
        t.join(timeout=30)
        assert not t.is_alive()
    return outcome


class TestSqliteArchiveRace:
    @pytest.fixture
    def dbs(self, tmp_path):
        path = str(tmp_path / "race.db")
        writer = SqliteDb(id="race-writer", db_file=path)
        archiver = SqliteDb(id="race-archiver", db_file=path)
        return writer, archiver

    def test_set_current_version_loses_to_a_concurrent_archive(self, dbs):
        writer, archiver = dbs
        cid = _mk_component(writer, "race-comp")

        outcome = _run_race(writer, archiver, cid, lambda: writer.set_current_version(cid, 1))

        # Exactly one winner: the archive. The loser reports False, same
        # verdict its pre-check gives for an already-archived row.
        assert outcome.get("result") is False, outcome
        row = archiver.get_component(cid, include_deleted=True)
        assert row["deleted_at"] is not None
        # The pointer never landed on the archived row.
        assert row["current_version"] == 2

    def test_upsert_component_loses_to_a_concurrent_archive(self, dbs):
        writer, archiver = dbs
        cid = _mk_component(writer, "race-upsert")

        outcome = _run_race(
            writer, archiver, cid, lambda: writer.upsert_component(component_id=cid, name="renamed-late")
        )

        assert isinstance(outcome.get("error"), ComponentArchivedError), outcome
        row = archiver.get_component(cid, include_deleted=True)
        assert row["deleted_at"] is not None
        # The archived row kept its pre-archive state.
        assert row["name"] == cid


def _postgres_reachable() -> bool:
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(DB_URL)
    except Exception:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    pytest.importorskip("psycopg")
    if not _postgres_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


class TestPostgresArchiveRace:
    @pytest.fixture
    def pg(self, _postgres_server):
        from sqlalchemy import text

        from agno.db.postgres import PostgresDb

        schema = f"archive_race_{uuid.uuid4().hex[:8]}"
        database = PostgresDb(db_url=DB_URL, db_schema=schema, id=f"archive-race-{schema}")
        yield database
        database.Session.remove()
        with database.db_engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.commit()
        database.db_engine.dispose()

    def test_set_current_version_loses_to_a_concurrent_archive(self, pg):
        cid = _mk_component(pg, "race-comp")

        # Same db object: threads get distinct pooled connections, so the
        # archive commits while the writer's UPDATE is held at the cursor.
        outcome = _run_race(pg, pg, cid, lambda: pg.set_current_version(cid, 1))

        assert outcome.get("result") is False, outcome
        row = pg.get_component(cid, include_deleted=True)
        assert row["deleted_at"] is not None
        assert row["current_version"] == 2

    def test_upsert_component_loses_to_a_concurrent_archive(self, pg):
        cid = _mk_component(pg, "race-upsert")

        outcome = _run_race(pg, pg, cid, lambda: pg.upsert_component(component_id=cid, name="renamed-late"))

        assert isinstance(outcome.get("error"), ComponentArchivedError), outcome
        row = pg.get_component(cid, include_deleted=True)
        assert row["deleted_at"] is not None
        assert row["name"] == cid
