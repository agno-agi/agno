"""Migration to 3.3.0: Company files move into one file system.

Runs on SQLite and PostgreSQL, sync and async. The PostgreSQL cases use the live pgvector container
(localhost:5532) and skip when psycopg or the server is absent. Each PostgreSQL test creates its own
database, because the move reads every Company namespace of the file table.
"""

import asyncio
from uuid import uuid4

import pytest

from agno.company.files import CompanyFiles
from agno.company.filesystem import company_filesystem
from agno.company.manager import CompanyManager
from agno.company.playbook import _defaults
from agno.db.migrations.versions.v3_3_0 import (
    CompanyFilesMigrationError,
    _file_table,
    _folders,
    _move,
    acompany_files_pending,
    acompany_notes_to_move,
    amove_company_files,
    amove_company_notes,
    company_files_pending,
    company_notes_to_move,
    move_company_files,
    move_company_notes,
)
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.fs import FileSystem

POSTGRES_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
BACKENDS = ["sqlite", "async-sqlite", "postgres", "async-postgres"]


def _postgres_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    try:
        import psycopg  # noqa: F401
        from sqlalchemy import create_engine, text
    except ImportError:
        return False
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


class Databases:
    """Databases of one kind for one test. ``new`` gives the database under test and a synchronous
    handle on the same data, used to write the layout from before 3.3.0 and to read the result."""

    def __init__(self, kind: str, tmp_path):
        self.kind, self.tmp_path = kind, tmp_path
        self.is_async = kind.startswith("async")
        self._opened: list = []
        self._postgres: list = []

    def new(self):
        if self.kind.endswith("sqlite"):
            path = str(self.tmp_path / f"{uuid4().hex[:8]}.db")
            reader = SqliteDb(db_file=path)
            db = AsyncSqliteDb(db_file=path) if self.is_async else SqliteDb(db_file=path)
        else:
            from sqlalchemy import create_engine, text
            from sqlalchemy.engine import make_url

            from agno.db.postgres import AsyncPostgresDb, PostgresDb

            name = "company_files_" + uuid4().hex[:12]
            admin = create_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
            with admin.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
            admin.dispose()
            self._postgres.append(name)
            url = make_url(POSTGRES_URL).set(database=name).render_as_string(hide_password=False)
            reader = PostgresDb(db_url=url)
            db = AsyncPostgresDb(db_url=url) if self.is_async else PostgresDb(db_url=url)
        self._opened.extend([(reader, False), (db, self.is_async)])
        return db, reader

    def run(self, sync_function, async_function, *args):
        """Call the synchronous or the asynchronous form, as the database under test needs."""
        if not self.is_async:
            return sync_function(*args)

        async def call():
            try:
                return await async_function(*args)
            finally:
                # Connections belong to this event loop: release them before it closes.
                for database in args:
                    engine = getattr(database, "db_engine", None)
                    if engine is not None and hasattr(engine, "sync_engine"):
                        await engine.dispose()

        return asyncio.run(call())

    def close(self) -> None:
        for database, is_async in self._opened:
            engine = database.db_engine
            if is_async:
                asyncio.run(engine.dispose())
            else:
                engine.dispose()
        if self._postgres:
            from sqlalchemy import create_engine, text

            admin = create_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
            with admin.connect() as conn:
                for name in self._postgres:
                    conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            admin.dispose()


@pytest.fixture(scope="module")
def postgres_server():
    return _postgres_reachable()


@pytest.fixture(params=BACKENDS)
def databases(request, tmp_path, postgres_server):
    if "postgres" in request.param and not postgres_server:
        pytest.skip(f"Postgres server not reachable at {POSTGRES_URL}")
    value = Databases(request.param, tmp_path)
    try:
        yield value
    finally:
        value.close()


def in_store(db):
    """The namespace of the Company file system, written as the file table takes it.

    The Company file system itself refuses every use while files wait to be moved, so a test that
    needs a file there before the migration writes it this way.
    """
    return FileSystem(db, namespace="company", user_scoped=False)


def rows(reader) -> dict:
    """Every row of the file table: (namespace, path) -> (content, version, created_at, updated_at, size)."""
    from sqlalchemy import inspect, select

    backend = FileSystem(reader, namespace="company", user_scoped=False).backend
    if not inspect(backend.db_engine).has_table(backend.table_name, schema=backend.db_schema):
        return {}
    table = backend.table
    with backend.db_engine.connect() as conn:
        found = conn.execute(
            select(
                table.c.namespace,
                table.c.path,
                table.c.content,
                table.c.version,
                table.c.created_at,
                table.c.updated_at,
                table.c.size_bytes,
                table.c.user_id,
            )
        ).all()
    assert all(row[7] == "" for row in found)
    return {(row[0], row[1]): tuple(row[2:7]) for row in found}


def old_layout(reader) -> dict:
    """Company records, and their files stored as 3.2.0 stores them. Returns the ids."""
    manager = CompanyManager(reader)
    goal = manager.create(name="Launch")
    # An id is stored in a namespace in lower case with other characters escaped.
    docs = manager.create(name="Docs", id="Docs Team")
    project = manager.create_project(goal_id=goal["id"], name="Plan")
    task = manager.create_task(goal_id=goal["id"], title="Write", project_id=project["id"])
    # Creating the records wrote nothing a file migration should find in the way.
    store = in_store(reader)
    for meta in store.list():
        store.delete(meta.path)

    def write(namespace: str, path: str, *contents: str) -> None:
        files = FileSystem(reader, namespace=namespace, user_scoped=False)
        for content in contents:
            files.write(path, content)

    write("company/wiki", "brief.md", "# Company\n\nWe ship.\n", "# Company\n\nWe ship weekly.\n")
    write("company/wiki", "people/ada.md", "Ada")
    write(f"company/products/{goal['id']}/wiki", "brief.md", "# Launch\n\nGo.\n")
    write(f"company/products/{goal['id']}/wiki", "research/notes.md", "one", "two", "three")
    write("company/products/Docs Team/wiki", "status.md", "# Docs status\n\nDrafting.\n")
    write(f"company/tasks/{task['id']}", "report.md", "The report")
    write(f"company/tasks/{task['id']}", "drafts/v1.md", "Draft")
    write("company/tasks/gone-task", "report.md", "A Task that was deleted")
    write("company/notes", "ideas.md", "A note", "A better note")
    # Not a file a person reads: it stays where it is.
    write(f"company/products/{goal['id']}/summary-state", "state.md", "delivered")
    return {"goal": goal["id"], "docs": docs["id"], "task": task["id"]}


def expected_after(before: dict, ids: dict) -> dict:
    """The rows after the move: the same content, version and timestamps under the new names."""
    folders = {
        "company/wiki": "wiki",
        "company/notes": "notes",
        f"company/products/{ids['goal']}/wiki": f"goals/{ids['goal']}",
        "company/products/docs%20team/wiki": "goals/Docs Team",
        f"company/tasks/{ids['task']}": f"tasks/{ids['task']}",
        "company/tasks/gone-task": "tasks/gone-task",
    }
    moved = {}
    for (namespace, path), values in before.items():
        if namespace in folders:
            moved[("company", f"{folders[namespace]}/{path}")] = values
        else:
            moved[(namespace, path)] = values
    return moved


def test_every_file_moves_to_its_tree_path_with_the_same_content_and_version(databases):
    db, reader = databases.new()
    ids = old_layout(reader)
    before = rows(reader)
    assert len(before) == 10 and before[("company/products/docs%20team/wiki", "status.md")][1] == 1
    assert before[("company/wiki", "brief.md")][1] == 2 and before[("company/notes", "ideas.md")][1] == 2

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    assert after == expected_after(before, ids)
    # Nothing is left in a namespace from before 3.3.0, and the summary state did not move.
    assert sorted({namespace for namespace, _ in after}) == [
        "company",
        f"company/products/{ids['goal']}/summary-state",
    ]
    assert after[("company", f"goals/{ids['goal']}/research/notes.md")][:2] == ("three", 3)

    # A second run finds nothing to move and changes nothing.
    assert databases.run(move_company_files, amove_company_files, db) is False
    assert rows(reader) == after

    # The tree reads every file where the move put it.
    files = CompanyFiles(reader, notes_db=reader)
    assert files.read("wiki/brief.md")["content"] == "# Company\n\nWe ship weekly.\n"
    assert files.read("wiki/brief.md")["version"] == 2
    assert files.read(f"goals/{ids['goal']}/research/notes.md")["content"] == "three"
    assert files.read("goals/Docs Team/status.md")["content"] == "# Docs status\n\nDrafting.\n"
    assert files.read(f"tasks/{ids['task']}/drafts/v1.md")["content"] == "Draft"
    assert files.read("notes/ideas.md")["content"] == "A better note"
    # A version check carries over: a save with the version from before the move is still refused.
    from agno.fs.errors import VersionConflictError

    with pytest.raises(VersionConflictError):
        files.write("wiki/brief.md", "late", expected_version=1)
    assert files.write("wiki/brief.md", "next", expected_version=2)["version"] == 3


def test_a_run_stopped_halfway_is_finished_by_the_next(databases):
    db, reader = databases.new()
    ids = old_layout(reader)
    before = rows(reader)
    # As a run that stopped after two folders leaves the table.
    done = {"company/wiki": "wiki", f"company/tasks/{ids['task']}": f"tasks/{ids['task']}"}
    with reader.Session() as sess, sess.begin():
        conn = sess.connection()
        assert _move(conn, _file_table(reader, conn), done, {}) == 4
    halfway = rows(reader)
    assert ("company", "wiki/brief.md") in halfway and ("company/notes", "ideas.md") in halfway

    assert databases.run(move_company_files, amove_company_files, db) is True

    assert rows(reader) == expected_after(before, ids)


def test_a_default_page_from_an_early_start_gives_way_to_the_page_that_moves_in(databases):
    db, reader = databases.new()
    ids = old_layout(reader)
    before = rows(reader)
    # The default pages are in the store already, as a wiki that was read while it held nothing creates
    # them. An instance still on 3.2.0 can write its pages after that.
    goal = CompanyManager(reader).get(ids["goal"])
    for folder, record in (("wiki", None), (f"goals/{ids['goal']}", goal)):
        for path, content in _defaults(record).items():
            in_store(reader).write(f"{folder}/{path}", content)
    seeded = rows(reader)
    assert seeded[("company", "wiki/brief.md")][1] == 1
    assert ("company", f"goals/{ids['goal']}/brief.md") in seeded

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    # The page that was in use moved in, with its version; a default page with no older page stays.
    assert after[("company", "wiki/brief.md")] == before[("company/wiki", "brief.md")]
    goal_brief = ("company", f"goals/{ids['goal']}/brief.md")
    assert after[goal_brief] == before[(f"company/products/{ids['goal']}/wiki", "brief.md")]
    assert after[("company", "wiki/status.md")] == seeded[("company", "wiki/status.md")]
    assert after[("company", f"goals/{ids['goal']}/status.md")] == seeded[("company", f"goals/{ids['goal']}/status.md")]
    assert not [key for key in after if key[0] in ("company/wiki", "company/notes")]


def test_a_different_file_already_at_the_new_path_stops_the_move(databases):
    db, reader = databases.new()
    ids = old_layout(reader)
    # Written after an early start, and not a default page: neither file may be lost.
    in_store(reader).write("notes/ideas.md", "Written on 3.3.0")
    in_store(reader).write(f"tasks/{ids['task']}/report.md", "The report")
    before = rows(reader)

    with pytest.raises(CompanyFilesMigrationError, match="notes/ideas.md"):
        databases.run(move_company_files, amove_company_files, db)
    # No row changed, in this folder or in any other.
    assert rows(reader) == before

    # With one of the two out of the way, the next run moves everything.
    in_store(reader).delete("notes/ideas.md")
    assert databases.run(move_company_files, amove_company_files, db) is True
    after = rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    # The same file already at the new path is not a clash.
    assert after[("company", f"tasks/{ids['task']}/report.md")][0] == "The report"
    assert not [key for key in after if key[0].startswith("company/tasks/") or key[0] == "company/notes"]


def test_a_database_with_no_file_table_is_left_without_one(databases):
    db, reader = databases.new()

    assert databases.run(move_company_files, amove_company_files, db) is False
    assert rows(reader) == {}
    from sqlalchemy import inspect

    backend = FileSystem(reader, namespace="company", user_scoped=False).backend
    assert not inspect(backend.db_engine).has_table(backend.table_name, schema=backend.db_schema)


def test_files_outside_the_company_namespaces_do_not_move(databases):
    db, reader = databases.new()
    for namespace in (
        "company-tests/x",
        "company/products/a/b/wiki",
        "company/products/alpha-data",
        "company/products/alpha/pages",
        "company/tasks",
        "company/tasks/a/b",
        "company/wikis",
        "notes",
    ):
        FileSystem(reader, namespace=namespace, user_scoped=False).write("keep.md", namespace)
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("ideas.md", "A note")
    before = rows(reader)

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    for key, values in before.items():
        if key != ("company/notes", "ideas.md"):
            assert after[key] == values, key
    assert len(after) == len(before)


@pytest.mark.parametrize(
    "namespace", ["company/wiki", "company/notes", "company/products/launch/wiki", "company/tasks/task-1"]
)
def test_files_are_pending_exactly_while_the_move_has_a_file_to_move(databases, namespace):
    db, reader = databases.new()
    # No file table yet.
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    # Files the move leaves where they are.
    for other in (
        "company",
        "default",
        "company/products/launch/summary-state",
        "company/products/a/b/wiki",
        "company/tasks/a/b",
        "company/wikis",
    ):
        FileSystem(reader, namespace=other, user_scoped=False).write("notes/keep.md", other)
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    assert databases.run(move_company_files, amove_company_files, db) is False

    FileSystem(reader, namespace=namespace, user_scoped=False).write("page.md", "Written on 3.2.0")
    assert databases.run(company_files_pending, acompany_files_pending, db) is True
    assert databases.run(move_company_files, amove_company_files, db) is True
    assert databases.run(company_files_pending, acompany_files_pending, db) is False


def test_a_database_that_keeps_no_file_table_has_no_file_pending():
    from agno.db.base import AsyncBaseDb
    from agno.db.in_memory import InMemoryDb

    class AsyncDocumentDb(AsyncBaseDb):
        """An asynchronous adapter that is neither SQLite nor PostgreSQL."""

    AsyncDocumentDb.__abstractmethods__ = frozenset()

    assert company_files_pending(InMemoryDb()) is False
    assert asyncio.run(acompany_files_pending(InMemoryDb())) is False
    assert asyncio.run(acompany_files_pending(AsyncDocumentDb())) is False


def test_the_async_pending_check_takes_a_synchronous_database(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    FileSystem(db, namespace="company/wiki", user_scoped=False).write("page.md", "Written on 3.2.0")
    assert asyncio.run(acompany_files_pending(db)) is True
    db.db_engine.dispose()


def test_a_file_table_from_before_user_partitions_is_read_without_being_refused(tmp_path):
    import sqlite3

    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    # A table as DbFileSystem created it before the user partition: every read of a file refuses it.
    with sqlite3.connect(os_file) as conn:
        conn.execute(
            "CREATE TABLE agno_fs (namespace VARCHAR NOT NULL, path VARCHAR NOT NULL, content TEXT NOT NULL, "
            "size_bytes BIGINT NOT NULL, version BIGINT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT, "
            "PRIMARY KEY (namespace, path))"
        )
        conn.execute("INSERT INTO agno_fs VALUES ('shared', 'd.md', 'd', 1, 3, 0, 0)")
    os_db, company_db = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)

    # It holds no Company file, and the checks say so: they read only the namespace and the path.
    assert company_files_pending(os_db) is False
    assert asyncio.run(acompany_files_pending(os_db)) is False
    assert company_notes_to_move(os_db, company_db) is False
    with sqlite3.connect(os_file) as conn:
        conn.execute("INSERT INTO agno_fs VALUES ('company/notes', 'ideas.md', 'A note', 6, 1, 0, 0)")
    assert company_files_pending(os_db) is True
    assert company_notes_to_move(os_db, company_db) is True
    os_db.db_engine.dispose()
    company_db.db_engine.dispose()


def test_notes_in_another_database_arrive_in_the_company_database_and_leave_the_source(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    notes = FileSystem(os_reader, namespace="company/notes", user_scoped=False)
    notes.write("ideas.md", "A note")
    notes.write("ideas.md", "A better note")
    notes.write("people/ada.md", "Ada")
    FileSystem(company_reader, namespace="company/wiki", user_scoped=False).write("brief.md", "# Company\n")
    FileSystem(os_reader, namespace="default", user_scoped=False).write("keep.md", "An agent's own file")
    # The migration runs on each database first, as it does for every table.
    assert databases.run(move_company_files, amove_company_files, os_db) is True
    assert databases.run(move_company_files, amove_company_files, company_db) is True
    in_source = rows(os_reader)
    assert ("company", "notes/ideas.md") in in_source and ("company", "notes/ideas.md") not in rows(company_reader)

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 2

    arrived, left = rows(company_reader), rows(os_reader)
    assert arrived[("company", "notes/ideas.md")] == in_source[("company", "notes/ideas.md")]
    assert arrived[("company", "notes/ideas.md")][:2] == ("A better note", 2)
    assert arrived[("company", "notes/people/ada.md")] == in_source[("company", "notes/people/ada.md")]
    assert arrived[("company", "wiki/brief.md")][0] == "# Company\n"
    assert left == {("default", "keep.md"): in_source[("default", "keep.md")]}
    # A second call moves nothing.
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 0
    assert rows(company_reader) == arrived and rows(os_reader) == left
    assert CompanyFiles(company_reader, notes_db=company_reader).read("notes/ideas.md")["version"] == 2


def test_a_note_move_stopped_after_the_copy_is_finished_by_the_next_call(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    in_store(os_reader).write("notes/ideas.md", "A note")
    in_store(os_reader).write("notes/more.md", "More")
    # One note was copied and the call stopped before the source was cleared.
    in_store(company_reader).write("notes/ideas.md", "A note")
    source_before = rows(os_reader)

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 2

    arrived = rows(company_reader)
    assert arrived[("company", "notes/ideas.md")][0] == "A note"
    assert arrived[("company", "notes/more.md")] == source_before[("company", "notes/more.md")]
    assert rows(os_reader) == {}


def test_a_different_note_in_the_company_database_stops_the_note_move(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    in_store(os_reader).write("notes/ideas.md", "From the AgentOS database")
    in_store(os_reader).write("notes/more.md", "More")
    in_store(company_reader).write("notes/ideas.md", "Written on 3.3.0")
    before = rows(os_reader), rows(company_reader)

    with pytest.raises(CompanyFilesMigrationError, match="notes/ideas.md"):
        databases.run(move_company_notes, amove_company_notes, os_db, company_db)

    assert (rows(os_reader), rows(company_reader)) == before


def test_moving_notes_between_two_handles_on_one_database_removes_nothing(databases):
    db, reader = databases.new()
    in_store(reader).write("notes/ideas.md", "A note")
    before = rows(reader)
    same = reader if not databases.is_async else db

    assert databases.run(move_company_notes, amove_company_notes, db, same) == 0
    assert rows(reader) == before
    if not databases.is_async:
        # Two handles on the same data are one database too.
        other_handle, _ = databases.new()
        del other_handle
        twin = (
            type(reader)(db_file=reader.db_file) if databases.kind == "sqlite" else type(reader)(db_url=reader.db_url)
        )
        try:
            assert move_company_notes(reader, twin) == 0
        finally:
            twin.db_engine.dispose()
        assert rows(reader) == before


def test_notes_still_in_the_namespace_from_before_are_moved_by_the_same_call(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    # The migration has not run on the AgentOS database: its notes are where 3.2.0 put them.
    notes = FileSystem(os_reader, namespace="company/notes", user_scoped=False)
    notes.write("ideas.md", "A note")
    notes.write("ideas.md", "A better note")
    notes.write("people/ada.md", "Ada")
    FileSystem(os_reader, namespace="company/wiki", user_scoped=False).write("brief.md", "Not a note")
    before = rows(os_reader)
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is True

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 2

    arrived = rows(company_reader)
    assert arrived[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    assert arrived[("company", "notes/people/ada.md")] == before[("company/notes", "people/ada.md")]
    # Only the notes moved: every other file of the AgentOS database is where it was.
    assert rows(os_reader) == {("company/wiki", "brief.md"): before[("company/wiki", "brief.md")]}
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is False


def test_moving_notes_again_changes_nothing_whatever_state_the_databases_are_in(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    # Neither database holds a file table yet.
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is False
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 0
    assert rows(os_reader) == {} and rows(company_reader) == {}

    in_store(os_reader).write("notes/ideas.md", "A note")
    in_store(os_reader).write("agents/keep.md", "Not a note")
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is True
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1
    settled = rows(os_reader), rows(company_reader)
    for _ in range(3):
        assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 0
        assert (rows(os_reader), rows(company_reader)) == settled
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is False
    # A note written in the Company database after the move is not a note to move, from either side.
    in_store(company_reader).write("notes/later.md", "Later")
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 0
    assert databases.run(company_notes_to_move, acompany_notes_to_move, company_db, company_db) is False
    assert ("company", "notes/later.md") in rows(company_reader)


def test_the_async_note_move_takes_a_synchronous_database_on_either_side(tmp_path):
    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    reader, company_reader = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)
    in_store(reader).write("notes/ideas.md", "A note")

    async def run() -> int:
        company = AsyncSqliteDb(db_file=company_file)
        try:
            assert await acompany_notes_to_move(reader, company) is True
            return await amove_company_notes(reader, company)
        finally:
            await company.db_engine.dispose()

    assert asyncio.run(run()) == 1
    assert rows(company_reader)[("company", "notes/ideas.md")][0] == "A note" and rows(reader) == {}
    reader.db_engine.dispose()
    company_reader.db_engine.dispose()


@pytest.mark.parametrize("is_async", [False, True])
def test_a_subclassed_adapter_has_its_files_and_notes_moved(tmp_path, is_async):
    base = AsyncSqliteDb if is_async else SqliteDb
    subclass = type("MyDb", (base,), {})
    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    reader, company_reader = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("ideas.md", "A note")
    FileSystem(company_reader, namespace="company/wiki", user_scoped=False).write("brief.md", "# Company\n")

    async def run() -> tuple:
        os_db, company_db = subclass(db_file=os_file), subclass(db_file=company_file)
        try:
            if not is_async:
                return (
                    move_company_files(company_db),
                    company_notes_to_move(os_db, company_db),
                    move_company_notes(os_db, company_db),
                )
            return (
                await amove_company_files(company_db),
                await acompany_notes_to_move(os_db, company_db),
                await amove_company_notes(os_db, company_db),
            )
        finally:
            for database in (os_db, company_db):
                disposed = database.db_engine.dispose()
                if is_async:
                    await disposed

    assert asyncio.run(run()) == (True, True, 1)
    assert sorted(rows(company_reader)) == [("company", "notes/ideas.md"), ("company", "wiki/brief.md")]
    assert rows(reader) == {}
    reader.db_engine.dispose()
    company_reader.db_engine.dispose()


def test_the_folder_of_a_namespace_uses_the_id_of_its_record():
    namespaces = [
        "company/wiki",
        "company/notes",
        "company/products/docs%20team/wiki",
        "company/products/launch/wiki",
        "company/products/orphan%2bone/wiki",
        "company/tasks/abc",
        "company/tasks/gone",
    ]
    goals = [{"id": "Docs Team", "name": "Docs", "objective": "Write"}, {"id": "launch", "name": "Launch"}]

    folders, defaults = _folders(namespaces, goals, ["ABC"])

    assert folders == {
        "company/wiki": "wiki",
        "company/notes": "notes",
        "company/products/docs%20team/wiki": "goals/Docs Team",
        "company/products/launch/wiki": "goals/launch",
        # No record is left: the folder keeps the name the namespace held, unescaped.
        "company/products/orphan%2bone/wiki": "goals/orphan+one",
        "company/tasks/abc": "tasks/ABC",
        "company/tasks/gone": "tasks/gone",
    }
    assert defaults["wiki"] == _defaults(None)
    assert defaults["goals/Docs Team"]["brief.md"] == "# Docs\n\nWrite\n"
    assert "goals/orphan+one" not in defaults and "notes" not in defaults
