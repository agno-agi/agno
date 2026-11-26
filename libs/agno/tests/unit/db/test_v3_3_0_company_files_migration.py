"""Migration to 3.3.0: Company files move into one file system.

Runs on SQLite and PostgreSQL, sync and async. The PostgreSQL cases use the live pgvector container
(localhost:5532) and skip when psycopg or the server is absent. Each PostgreSQL test creates its own
database, because the move reads every Company namespace of the file table.
"""

import asyncio
from uuid import uuid4

import pytest

from agno.company.files import CompanyFiles
from agno.company.manager import CompanyManager
from agno.company.playbook import _defaults
from agno.db.migrations.versions.v3_3_0 import (
    CompanyFilesMigrationError,
    _file_backend,
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


def used_by_company(reader) -> None:
    """A Company table, as Company leaves one in a database it worked on."""
    reader._get_table("goals", create_table_if_not_found=True)


def used_by_super_agent(reader) -> None:
    """A session of Super Agent, as a chat with it leaves one in the AgentOS database."""
    from agno.session import TeamSession

    reader.upsert_session(TeamSession(session_id=uuid4().hex, team_id="superagent", created_at=1))


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
        "company/products/docs%20team/wiki": "goals/Docs%20Team",
        f"company/tasks/{ids['task']}": f"tasks/{ids['task']}",
        # No Task has this id any more: its files stay where they are.
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
    # The summary state did not move, and the files of a Task that is gone stay: nothing else is left behind.
    assert sorted({namespace for namespace, _ in after}) == [
        "company",
        f"company/products/{ids['goal']}/summary-state",
        "company/tasks/gone-task",
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
        assert _move(conn, _file_backend(reader, conn).table, done, {}) == 4
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


def test_a_default_page_an_older_instance_wrote_after_the_move_does_not_stop_the_next_run(databases):
    db, reader = databases.new()
    ids = old_layout(reader)
    assert databases.run(move_company_files, amove_company_files, db) is True
    moved = rows(reader)
    assert moved[("company", "wiki/brief.md")][:2] == ("# Company\n\nWe ship weekly.\n", 2)
    # An instance still on 3.2.0 reads a wiki it finds empty, and writes the default pages where it keeps them.
    goal = CompanyManager(reader).get(ids["goal"])
    for namespace, record in (("company/wiki", None), (f"company/products/{ids['goal']}/wiki", goal)):
        for path, content in _defaults(record).items():
            FileSystem(reader, namespace=namespace, user_scoped=False).write(path, content)

    databases.run(move_company_files, amove_company_files, db)

    after = rows(reader)
    # The edited pages stay as they were, and the default pages written over them are gone.
    assert after[("company", "wiki/brief.md")] == moved[("company", "wiki/brief.md")]
    goal_brief = ("company", f"goals/{ids['goal']}/brief.md")
    assert after[goal_brief] == moved[goal_brief]
    # A default page with no page at its new path moves in.
    assert after[("company", "wiki/status.md")][:2] == (_defaults(None)["status.md"], 1)
    assert not [key for key in after if key[0] in ("company/wiki", f"company/products/{ids['goal']}/wiki")]
    assert databases.run(company_files_pending, acompany_files_pending, db) is False

    # A page an older instance edited is not a default page: it still stops the move.
    FileSystem(reader, namespace="company/wiki", user_scoped=False).write("brief.md", "Edited on 3.2.0")
    with pytest.raises(CompanyFilesMigrationError, match="wiki/brief.md"):
        databases.run(move_company_files, amove_company_files, db)


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
    left = [key for key in after if key[0].startswith("company/tasks/") or key[0] == "company/notes"]
    assert left == [("company/tasks/gone-task", "report.md")]


def test_a_database_with_no_file_table_is_left_without_one(databases):
    db, reader = databases.new()

    assert databases.run(move_company_files, amove_company_files, db) is False
    assert rows(reader) == {}
    from sqlalchemy import inspect

    backend = FileSystem(reader, namespace="company", user_scoped=False).backend
    assert not inspect(backend.db_engine).has_table(backend.table_name, schema=backend.db_schema)


def test_a_database_that_shows_no_use_of_company_or_super_agent_keeps_its_files(databases):
    from agno.db.migrations.manager import MigrationManager

    db, reader = databases.new()
    # An agent's own shared stores, named as Company named its namespaces before 3.3.0.
    FileSystem(reader, namespace="company/wiki", user_scoped=False).write("page.md", "An agent's page")
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("ideas.md", "An agent's note")
    FileSystem(reader, namespace="company/tasks/review", user_scoped=False).write("report.md", "An agent's report")
    FileSystem(reader, namespace="company", user_scoped=False).write("notes/mine.md", "An agent's file")
    # Sessions of the agent, and no session of Super Agent.
    from agno.session import AgentSession

    reader.upsert_session(AgentSession(session_id="chat", agent_id="writer", created_at=1))
    before = rows(reader)

    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    assert databases.run(move_company_files, amove_company_files, db) is False

    async def migrate(database) -> None:
        await MigrationManager(database).up()

    databases.run(lambda database: asyncio.run(migrate(database)), migrate, db)
    assert rows(reader) == before
    assert [meta.path for meta in FileSystem(reader, namespace="company/wiki", user_scoped=False).list()] == ["page.md"]

    # Once Super Agent has chatted on the database, the notes are its own and they move.
    used_by_super_agent(reader)
    assert databases.run(company_files_pending, acompany_files_pending, db) is True


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
    used_by_super_agent(reader)
    before = rows(reader)

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    for key, values in before.items():
        if key != ("company/notes", "ideas.md"):
            assert after[key] == values, key
    assert len(after) == len(before)


@pytest.mark.parametrize("kind", ["wiki", "notes", "goal", "task"])
def test_files_are_pending_exactly_while_the_move_has_a_file_to_move(databases, kind):
    db, reader = databases.new()
    # No file table yet.
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    manager = CompanyManager(reader)
    goal = manager.create(name="Launch", id="launch")
    project = manager.create_project(goal_id=goal["id"], name="Plan")
    task = manager.create_task(goal_id=goal["id"], title="Write", project_id=project["id"])
    # Files the move leaves where they are: the last three are named as a Goal or a Task that this database does not hold.
    for other in (
        "company",
        "default",
        "company/products/launch/summary-state",
        "company/wikis",
        "company/products/a/b/wiki",
        "company/tasks/a/b",
        "company/tasks/gone",
    ):
        FileSystem(reader, namespace=other, user_scoped=False).write("notes/keep.md", other)
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    assert databases.run(move_company_files, amove_company_files, db) is False

    namespace = {
        "wiki": "company/wiki",
        "notes": "company/notes",
        "goal": "company/products/launch/wiki",
        "task": f"company/tasks/{task['id']}",
    }[kind]
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
    used_by_company(db)
    assert asyncio.run(acompany_files_pending(db)) is True
    db.db_engine.dispose()


def test_notes_in_another_database_arrive_in_the_company_database_and_leave_the_source(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    notes = FileSystem(os_reader, namespace="company/notes", user_scoped=False)
    notes.write("ideas.md", "A note")
    notes.write("ideas.md", "A better note")
    notes.write("people/ada.md", "Ada")
    FileSystem(company_reader, namespace="company/wiki", user_scoped=False).write("brief.md", "# Company\n")
    FileSystem(os_reader, namespace="default", user_scoped=False).write("keep.md", "An agent's own file")
    used_by_super_agent(os_reader)
    used_by_company(company_reader)
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
    used_by_company(company_reader)

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


def test_the_migration_reports_each_path_that_ends_up_over_the_write_limit(databases, caplog):
    import logging

    from agno.company.filesystem import company_filesystem
    from agno.fs._paths import MAX_PATH_CHARS, MAX_SEGMENTS
    from agno.fs.errors import InvalidPathError

    db, reader = databases.new()
    manager = CompanyManager(reader)
    goal = manager.create(name="Launch")
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    # As deep and as long as the wiki API of 3.2.0 accepts: fine in its own namespace, too long once inside a folder.
    deep = "/".join(f"d{index}" for index in range(MAX_SEGMENTS - 1)) + "/page.md"
    long = "/".join(["x" * 120] * 4) + "/page.md"
    assert len(deep.split("/")) == MAX_SEGMENTS and MAX_PATH_CHARS - 40 < len(long) <= MAX_PATH_CHARS
    wiki = FileSystem(reader, namespace="company/wiki", user_scoped=False)
    wiki.write(deep, "Deep")
    wiki.write("brief.md", "Fits")
    pages = FileSystem(reader, namespace=f"company/products/{goal['id']}/wiki", user_scoped=False)
    pages.write(long, "Long")
    pages.write("a/b/research.md", "Fits")
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("ideas.md", "Fits")

    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="agno"):
            assert databases.run(move_company_files, amove_company_files, db) is True

        over = [f"goals/{goal['id']}/{long}", f"wiki/{deep}"]
        assert len(over[0]) > MAX_PATH_CHARS and len(over[1].split("/")) > MAX_SEGMENTS
        reports = [r.getMessage() for r in caplog.records if "longer than a write accepts" in r.getMessage()]
        assert len(reports) == 1 and reports[0].startswith("2 Company files")
        assert all(path in reports[0] for path in over)
        assert "brief.md" not in reports[0] and "research.md" not in reports[0] and "ideas.md" not in reports[0]
        # Each is stored, read and listed whatever its length. Only a write of such a path is refused.
        stored = rows(reader)
        assert stored[("company", over[0])][0] == "Long" and stored[("company", over[1])][0] == "Deep"
        whole = company_filesystem(reader)
        assert whole.read(over[0]) == "Long" and whole.read(over[1]) == "Deep"
        assert sorted(meta.path for meta in whole.list("wiki")) == sorted(["wiki/brief.md", over[1]])
        with pytest.raises(InvalidPathError):
            whole.write(over[1], "Changed")
        # A second run has nothing to move and nothing to report.
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="agno"):
            assert databases.run(move_company_files, amove_company_files, db) is False
        assert not [r for r in caplog.records if "longer than a write accepts" in r.getMessage()]
    finally:
        agno_logger.removeHandler(caplog.handler)


# ------------------------------------------------------------------ one database reached two ways


def every_row(reader) -> dict:
    """Every row of the file table, a user's rows included: (namespace, user_id, path) -> (content, version)."""
    from sqlalchemy import inspect, select

    backend = FileSystem(reader, namespace="company", user_scoped=False).backend
    if not inspect(backend.db_engine).has_table(backend.table_name, schema=backend.db_schema):
        return {}
    table = backend.table
    with backend.db_engine.connect() as conn:
        found = conn.execute(select(table.c.namespace, table.c.user_id, table.c.path, table.c.content, table.c.version))
        return {(row[0], row[1], row[2]): (row[3], row[4]) for row in found}


def _run(databases_are_async: bool, sync_function, async_function, *args):
    if not databases_are_async:
        return sync_function(*args)

    async def call():
        try:
            return await async_function(*args)
        finally:
            for database in args:
                engine = getattr(database, "db_engine", None)
                if engine is not None and hasattr(engine, "sync_engine"):
                    await engine.dispose()

    return asyncio.run(call())


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("spelling", ["dots", "link", "relative"])
def test_one_sqlite_file_named_two_ways_is_one_place_and_keeps_its_notes(tmp_path, monkeypatch, spelling, is_async):
    folder = tmp_path / "data"
    folder.mkdir()
    path = folder / "agentos.db"
    reader = SqliteDb(db_file=str(path))
    in_store(reader).write("notes/ideas.md", "A note")
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("older.md", "An older note")
    before = every_row(reader)
    cls = AsyncSqliteDb if is_async else SqliteDb
    scheme = "sqlite+aiosqlite" if is_async else "sqlite"
    # The same file, written in the URL as an operator may write it.
    if spelling == "dots":
        other = cls(db_url=f"{scheme}:///{folder}/../data/agentos.db")
    elif spelling == "link":
        link = tmp_path / "link.db"
        link.symlink_to(path)
        other = cls(db_url=f"{scheme}:///{link}")
    else:
        monkeypatch.chdir(tmp_path)
        other = cls(db_url=f"{scheme}:///data/agentos.db")
    first = cls(db_file=str(path))

    # The notes are in the Company database already: there is nothing to move, and nothing is removed.
    assert _run(is_async, company_notes_to_move, acompany_notes_to_move, first, other) is False
    assert _run(is_async, move_company_notes, amove_company_notes, first, other) == 0
    assert _run(is_async, move_company_notes, amove_company_notes, other, first) == 0
    assert every_row(reader) == before
    reader.db_engine.dispose()
    if not is_async:
        first.db_engine.dispose()
        other.db_engine.dispose()


@pytest.mark.parametrize("is_async", [False, True])
def test_one_postgres_database_named_by_two_hosts_is_one_place_and_keeps_its_notes(postgres_server, is_async):
    if not postgres_server:
        pytest.skip(f"Postgres server not reachable at {POSTGRES_URL}")
    from sqlalchemy.engine import make_url

    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    databases = Databases("async-postgres" if is_async else "postgres", None)
    try:
        db, reader = databases.new()
        in_store(reader).write("notes/ideas.md", "A note")
        before = every_row(reader)
        by_name = make_url(db.db_url) if isinstance(db.db_url, str) else db.db_engine.url
        assert by_name.host == "localhost"
        by_address = by_name.set(host="127.0.0.1").render_as_string(hide_password=False)
        other = (AsyncPostgresDb if is_async else PostgresDb)(db_url=by_address)
        databases._opened.append((other, is_async))

        assert _run(is_async, company_notes_to_move, acompany_notes_to_move, db, other) is False
        assert _run(is_async, move_company_notes, amove_company_notes, db, other) == 0
        assert _run(is_async, move_company_notes, amove_company_notes, other, db) == 0
        assert every_row(reader) == before
    finally:
        databases.close()


def test_two_in_memory_databases_are_two_places():
    source, company = SqliteDb(db_url="sqlite://"), SqliteDb(db_url="sqlite://")
    in_store(source).write("notes/ideas.md", "A note")

    assert company_notes_to_move(source, company) is True
    assert move_company_notes(source, company) == 1
    assert every_row(company) == {("company", "", "notes/ideas.md"): ("A note", 1)}
    assert every_row(source) == {}
    # One in-memory database is one place.
    assert company_notes_to_move(company, company) is False


@pytest.mark.parametrize("is_async", [False, True])
def test_a_wrong_answer_about_the_place_of_a_database_removes_no_note(tmp_path, monkeypatch, is_async):
    from agno.db.migrations.versions import v3_3_0

    path = str(tmp_path / "agentos.db")
    reader = SqliteDb(db_file=path)
    in_store(reader).write("notes/ideas.md", "A note")
    before = every_row(reader)
    cls = AsyncSqliteDb if is_async else SqliteDb
    first, twin = cls(db_file=path), cls(db_file=path)
    # However the two handles are told apart, a note is removed only once it is seen in another table.
    answers = iter(range(1000))
    monkeypatch.setattr(v3_3_0, "_file_place", lambda sess, db: ("somewhere", next(answers)))

    assert _run(is_async, move_company_notes, amove_company_notes, first, twin) == 0
    assert every_row(reader) == before
    reader.db_engine.dispose()
    if not is_async:
        first.db_engine.dispose()
        twin.db_engine.dispose()


@pytest.mark.parametrize("is_async", [False, True])
def test_a_note_the_company_database_is_not_seen_to_hold_stays_in_the_agentos_database(tmp_path, monkeypatch, is_async):
    from agno.db.migrations.versions import v3_3_0

    cls = AsyncSqliteDb if is_async else SqliteDb
    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    os_reader, company_reader = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)
    in_store(os_reader).write("notes/ideas.md", "A note")
    in_store(os_reader).write("notes/more.md", "More")
    before = every_row(os_reader)
    # A write that stores one note of the two, whatever the reason.
    write = v3_3_0._write_notes
    monkeypatch.setattr(v3_3_0, "_write_notes", lambda sess, db, notes: write(sess, db, notes[:1]))

    assert _run(is_async, move_company_notes, amove_company_notes, cls(db_file=os_file), cls(db_file=company_file)) == 1

    # The note that arrived left the AgentOS database. The other is still there, as it was.
    arrived = every_row(company_reader)
    assert len(arrived) == 1
    left = every_row(os_reader)
    assert len(left) == 1 and set(arrived) | set(left) == set(before)
    assert all(before[key] == value for key, value in {**arrived, **left}.items())
    os_reader.db_engine.dispose()
    company_reader.db_engine.dispose()


@pytest.mark.parametrize("is_async", [False, True])
def test_a_note_changed_in_the_company_database_after_the_copy_stays_in_the_agentos_database(
    tmp_path, monkeypatch, is_async
):
    from agno.db.migrations.versions import v3_3_0

    cls = AsyncSqliteDb if is_async else SqliteDb
    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    os_reader, company_reader = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)
    in_store(os_reader).write("notes/ideas.md", "A note")
    before = every_row(os_reader)
    write = v3_3_0._write_notes

    def write_then_someone_edits(sess, db, notes) -> None:
        write(sess, db, notes)
        files = v3_3_0._file_backend(db, sess.connection()).table
        sess.connection().execute(files.update().values(content="Edited by someone else"))

    monkeypatch.setattr(v3_3_0, "_write_notes", write_then_someone_edits)

    # The Company database does not hold the note as it was copied, so the AgentOS database keeps its copy.
    assert _run(is_async, move_company_notes, amove_company_notes, cls(db_file=os_file), cls(db_file=company_file)) == 0
    assert every_row(os_reader) == before
    os_reader.db_engine.dispose()
    company_reader.db_engine.dispose()


def test_two_moves_of_the_same_notes_at_once_move_each_note_once(databases):
    import threading

    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    for index in range(20):
        in_store(os_reader).write(f"notes/n{index}.md", f"Note {index}")
        in_store(os_reader).write(f"notes/n{index}.md", f"Note {index}, again")
    before = rows(os_reader)
    kind = type(os_reader)
    where = (
        (lambda reader: {"db_file": reader.db_file})
        if databases.kind.endswith("sqlite")
        else (lambda reader: {"db_url": reader.db_url})
    )
    handles = [(kind(**where(os_reader)), kind(**where(company_reader))) for _ in range(2)]
    start = threading.Barrier(2)
    moved: list = []
    failed: list = []

    def move(source, company) -> None:
        start.wait()
        try:
            moved.append(move_company_notes(source, company))
        except Exception as exc:  # noqa: BLE001
            failed.append(exc)

    threads = [threading.Thread(target=move, args=pair) for pair in handles]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for source, company in handles:
        source.db_engine.dispose()
        company.db_engine.dispose()

    # Neither move fails, and between them every note is in the Company database once, as it was.
    assert failed == []
    assert rows(company_reader) == before and rows(os_reader) == {}
    assert sum(moved) == 20


def test_a_move_that_loses_the_race_to_store_a_note_finishes_with_what_is_stored(databases, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from agno.db.migrations.versions import v3_3_0

    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    in_store(os_reader).write("notes/ideas.md", "A note")
    before = rows(os_reader)
    write = v3_3_0._write_notes
    calls: list = []

    def another_move_stores_it_first(sess, db, notes) -> None:
        calls.append(len(notes))
        if len(calls) == 1:
            # What the losing side of two moves at once gets from the database.
            write(sess, db, notes)
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        write(sess, db, notes)

    monkeypatch.setattr(v3_3_0, "_write_notes", another_move_stores_it_first)

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1
    assert calls == [1, 1]
    assert rows(company_reader) == before and rows(os_reader) == {}


# ------------------------------------------------------------------ a user's own files


def test_files_in_a_user_partition_are_not_company_files(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    used_by_company(os_reader)
    # An agent's own store, partitioned by user, that happens to use these names.
    own = FileSystem(os_reader, namespace="company", user_scoped=True)
    own.resolve(user_id="alice").write("notes/private.md", "Alice's own")
    older = FileSystem(os_reader, namespace="company/notes", user_scoped=True)
    older.resolve(user_id="alice").write("diary.md", "Alice's diary")
    FileSystem(os_reader, namespace="company/wiki", user_scoped=True).resolve(user_id="bob").write("x.md", "Bob's")
    before = every_row(os_reader)
    assert {key[1] for key in before} == {"alice", "bob"}
    assert len(before) == 3

    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is False
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 0
    assert databases.run(company_files_pending, acompany_files_pending, os_db) is False
    assert databases.run(move_company_files, amove_company_files, os_db) is False
    assert every_row(os_reader) == before and every_row(company_reader) == {}

    # A shared note beside them is a note, and it moves alone.
    in_store(os_reader).write("notes/ideas.md", "A note")
    assert databases.run(company_notes_to_move, acompany_notes_to_move, os_db, company_db) is True
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1
    assert every_row(os_reader) == before
    assert every_row(company_reader) == {("company", "", "notes/ideas.md"): ("A note", 1)}

    # A shared page beside a user's page in one namespace moves alone too, and so does a shared note left behind.
    FileSystem(os_reader, namespace="company/wiki", user_scoped=False).write("x.md", "The company's")
    FileSystem(os_reader, namespace="company/notes", user_scoped=False).write("diary.md", "A shared note")
    assert databases.run(company_files_pending, acompany_files_pending, os_db) is True
    assert databases.run(move_company_files, amove_company_files, os_db) is True
    assert every_row(os_reader) == {
        **before,
        ("company", "", "wiki/x.md"): ("The company's", 1),
        ("company", "", "notes/diary.md"): ("A shared note", 1),
    }
    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1
    assert every_row(os_reader) == {**before, ("company", "", "wiki/x.md"): ("The company's", 1)}


# ------------------------------------------------------------------ the folder of an id


def write_3_2_0(reader, namespace: str, path: str, *contents: str) -> None:
    """A file where agno 3.2.0 stored it: the namespace is lower-cased and escaped as that version did."""
    files = FileSystem(reader, namespace=namespace, user_scoped=False)
    for content in contents:
        files.write(path, content)


def test_an_id_with_a_slash_keeps_its_own_folder_through_the_migration(databases):
    from agno.company.filesystem import folder_name

    db, reader = databases.new()
    manager = CompanyManager(reader)
    for goal_id in ("team", "team/growth"):
        manager.create(name=goal_id, id=goal_id)
    project = manager.create_project(goal_id="team", name="Plan")
    task = manager.create_task(goal_id="team", title="Write", project_id=project["id"])
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    # 3.2.0 kept a slash in a namespace as it is, so each of the two Goals had a namespace of its own.
    write_3_2_0(reader, "company/products/team/wiki", "status.md", "The team")
    write_3_2_0(reader, "company/products/team/wiki", "growth/plan.md", "The team's own page about growth")
    write_3_2_0(reader, "company/products/team/growth/wiki", "status.md", "Growth", "Growth, twice")
    write_3_2_0(reader, f"company/tasks/{task['id']}", "report.md", "The report")
    before = rows(reader)
    assert sorted({namespace for namespace, _ in before}) == [
        "company/products/team/growth/wiki",
        "company/products/team/wiki",
        f"company/tasks/{task['id'].lower()}",
    ]

    assert databases.run(company_files_pending, acompany_files_pending, db) is True
    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    assert folder_name("team/growth") == "team%2fgrowth"
    assert after == {
        ("company", "goals/team/status.md"): before[("company/products/team/wiki", "status.md")],
        ("company", "goals/team/growth/plan.md"): before[("company/products/team/wiki", "growth/plan.md")],
        ("company", "goals/team%2fgrowth/status.md"): before[("company/products/team/growth/wiki", "status.md")],
        ("company", f"tasks/{task['id']}/report.md"): before[(f"company/tasks/{task['id'].lower()}", "report.md")],
    }
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    # Each Goal reads its own pages and none of the other's.
    listed = {
        goal_id: sorted(page.path for page in manager.list_wiki(goal_id, limit=100)[0])
        for goal_id in ("team", "team/growth")
    }
    assert listed == {"team": ["brief.md", "growth/plan.md", "status.md"], "team/growth": ["brief.md", "status.md"]}
    assert manager.read_wiki("team/growth", "status.md").content == "Growth, twice"
    assert manager.read_wiki("team/growth", "status.md").metadata.version == 2
    assert manager.read_wiki("team", "status.md").content == "The team"


def test_an_id_that_is_not_in_normal_form_is_read_where_the_migration_put_it(databases):
    import unicodedata

    db, reader = databases.new()
    manager = CompanyManager(reader)
    decomposed = "café"
    assert unicodedata.normalize("NFC", decomposed) != decomposed
    manager.create(name="Cafe", id=decomposed)
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    # 3.2.0 composed and escaped the id in the namespace.
    write_3_2_0(reader, f"company/products/{decomposed}/wiki", "status.md", "Open", "Open late")
    before = rows(reader)
    assert list(before) == [("company/products/caf%c3%a9/wiki", "status.md")]

    assert databases.run(move_company_files, amove_company_files, db) is True

    assert rows(reader) == {
        ("company", "goals/cafe%cc%81/status.md"): before[("company/products/caf%c3%a9/wiki", "status.md")]
    }
    page = manager.read_wiki(decomposed, "status.md")
    assert (page.content, page.metadata.version) == ("Open late", 2)


def test_two_goals_that_shared_one_namespace_keep_their_pages_in_place_and_are_reported(databases, caplog):
    import logging

    from agno.db.migrations.versions.v3_3_0 import acompany_files_left, company_files_left

    db, reader = databases.new()
    manager = CompanyManager(reader)
    for goal_id in ("Docs", "docs", "launch"):
        manager.create(name=goal_id, id=goal_id)
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    # 3.2.0 lower-cased an id in the namespace, so the two Goals read and wrote the same pages.
    write_3_2_0(reader, "company/products/Docs/wiki", "status.md", "Drafting")
    write_3_2_0(reader, "company/products/docs/wiki", "research/notes.md", "Found")
    write_3_2_0(reader, "company/products/launch/wiki", "status.md", "Go")
    before = rows(reader)
    shared = "company/products/docs/wiki"
    assert sorted(key for key in before if key[0] == shared) == [(shared, "research/notes.md"), (shared, "status.md")]

    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="agno"):
            assert databases.run(move_company_files, amove_company_files, db) is True
    finally:
        agno_logger.removeHandler(caplog.handler)

    after = rows(reader)
    # The Goal with a namespace of its own moved. The shared pages are where they were, each as it was.
    assert after[("company", "goals/launch/status.md")] == before[("company/products/launch/wiki", "status.md")]
    for key in ((shared, "status.md"), (shared, "research/notes.md")):
        assert after[key] == before[key]
    assert len(after) == len(before)
    # They are reported by path with the Goals that shared them, and they do not keep the migration pending.
    left = databases.run(company_files_left, acompany_files_left, db)
    assert left == [
        {"namespace": shared, "paths": ["research/notes.md", "status.md"], "owners": ["Docs", "docs"]},
    ]
    report = "\n".join(record.getMessage() for record in caplog.records)
    assert shared in report and "research/notes.md" in report and "Docs, docs" in report
    assert "move_company_files" in report and "owners=" in report
    assert databases.run(company_files_pending, acompany_files_pending, db) is False

    # What an operator does next: name the Goal that keeps them.
    assert (
        databases.run(
            lambda d: move_company_files(d, owners={shared: "docs"}),
            lambda d: amove_company_files(d, owners={shared: "docs"}),
            db,
        )
        is True
    )
    assert rows(reader)[("company", "goals/docs/status.md")] == before[(shared, "status.md")]
    assert rows(reader)[("company", "goals/docs/research/notes.md")] == before[(shared, "research/notes.md")]
    assert databases.run(company_files_left, acompany_files_left, db) == []
    assert manager.read_wiki("docs", "status.md").content == "Drafting"
    # The other Goal has its own folder now, and none of these pages.
    assert manager.list_wiki("Docs", limit=100)[1] == 2


def test_an_owner_named_by_hand_must_be_a_record_of_this_database(databases):
    db, reader = databases.new()
    manager = CompanyManager(reader)
    for goal_id in ("Docs", "docs"):
        manager.create(name=goal_id, id=goal_id)
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    write_3_2_0(reader, "company/products/docs/wiki", "status.md", "Drafting")
    write_3_2_0(reader, "company/tasks/gone-task", "report.md", "Of a Task that was deleted")
    write_3_2_0(reader, "company/wiki", "people.md", "Ada")
    before = rows(reader)

    def move(owners: dict):
        return databases.run(
            lambda d: move_company_files(d, owners=owners), lambda d: amove_company_files(d, owners=owners), db
        )

    for owners, message in (
        ({"company/products/docs/wiki": "nobody"}, "not the id of a Goal"),
        ({"company/tasks/gone-task": "nobody"}, "not the id of a Task"),
        ({"company/wiki": "docs"}, "takes no owner"),
        ({"company/products/elsewhere/wiki": "docs"}, "takes no owner"),
    ):
        with pytest.raises(CompanyFilesMigrationError, match=message):
            move(owners)
        # A refused owner moves nothing, not even the files that need none.
        assert rows(reader) == before
    assert move({"company/products/docs/wiki": "Docs"}) is True
    after = rows(reader)
    assert after[("company", "goals/Docs/status.md")] == before[("company/products/docs/wiki", "status.md")]
    assert after[("company", "wiki/people.md")] == before[("company/wiki", "people.md")]
    assert after[("company/tasks/gone-task", "report.md")] == before[("company/tasks/gone-task", "report.md")]
    # Nothing waits there now, so a name for it is refused.
    with pytest.raises(CompanyFilesMigrationError, match="takes no owner|No file waits"):
        move({"company/products/docs/wiki": "docs"})


def test_a_task_whose_id_is_not_plain_gets_the_folder_of_its_id(databases):
    from sqlalchemy import text

    db, reader = databases.new()
    manager = CompanyManager(reader)
    goal = manager.create(name="Launch", id="launch")
    project = manager.create_project(goal_id=goal["id"], name="Plan")
    task = manager.create_task(goal_id=goal["id"], title="Write", project_id=project["id"])
    # Task ids are generated. One written another way is still named as one segment that keeps it apart.
    schema = getattr(reader, "db_schema", None)
    table = f'"{schema}"."{reader.tasks_table_name}"' if schema else f'"{reader.tasks_table_name}"'
    with reader.Session() as sess, sess.begin():
        sess.execute(text(f"UPDATE {table} SET id = :new WHERE id = :old"), {"new": "Task A/1", "old": task["id"]})
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    write_3_2_0(reader, "company/tasks/Task A/1", "report.md", "The report")
    before = rows(reader)
    assert list(before) == [("company/tasks/task%20a/1", "report.md")]

    assert databases.run(move_company_files, amove_company_files, db) is True

    assert rows(reader) == {
        ("company", "tasks/Task%20A%2f1/report.md"): before[("company/tasks/task%20a/1", "report.md")]
    }


def test_files_whose_goal_or_task_is_not_in_this_database_stay_and_are_reported(databases):
    from agno.db.migrations.versions.v3_3_0 import acompany_files_left, company_files_left

    db, reader = databases.new()
    CompanyManager(reader).create(name="Launch", id="launch")
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    write_3_2_0(reader, "company/products/gone/wiki", "status.md", "Of a Goal that was deleted")
    write_3_2_0(reader, "company/tasks/gone-task", "report.md", "Of a Task that was deleted")
    write_3_2_0(reader, "company/notes", "ideas.md", "A note")
    before = rows(reader)

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    for key in (("company/products/gone/wiki", "status.md"), ("company/tasks/gone-task", "report.md")):
        assert after[key] == before[key]
    assert databases.run(company_files_left, acompany_files_left, db) == [
        {"namespace": "company/products/gone/wiki", "paths": ["status.md"], "owners": []},
        {"namespace": "company/tasks/gone-task", "paths": ["report.md"], "owners": []},
    ]
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    assert databases.run(move_company_files, amove_company_files, db) is False


# ------------------------------------------------------------------ a file table from before user partitions


def _outdated_file_table(path: str, *rows_: tuple) -> None:
    """A file table as DbFileSystem created it before the user partition: every file operation refuses it."""
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE agno_fs (namespace VARCHAR NOT NULL, path VARCHAR NOT NULL, content TEXT NOT NULL, "
            "size_bytes BIGINT NOT NULL, version BIGINT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT, "
            "PRIMARY KEY (namespace, path))"
        )
        conn.executemany("INSERT INTO agno_fs VALUES (?, ?, ?, 1, 1, 0, 0)", rows_)


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("named_like_company", [False, True])
def test_a_file_table_from_before_user_partitions_does_not_stop_the_migration(tmp_path, named_like_company, is_async):
    import sqlite3

    from agno.db.migrations.manager import MigrationManager

    path = str(tmp_path / "agentos.db")
    rows_ = [("shared", "d.md", "d")]
    if named_like_company:
        # No version that had Company could write to this table, so these are an agent's files.
        rows_ += [("company/wiki", "x.md", "x"), ("company/notes", "y.md", "y"), ("company", "notes/z.md", "z")]
    _outdated_file_table(path, *rows_)
    db = (AsyncSqliteDb if is_async else SqliteDb)(db_file=path)
    other = SqliteDb(db_file=str(tmp_path / "company.db"))

    async def migrate() -> tuple:
        try:
            await MigrationManager(db).up()
            if is_async:
                return (
                    await acompany_files_pending(db),
                    await amove_company_files(db),
                    await acompany_notes_to_move(db, other),
                    await amove_company_notes(db, other),
                )
            return (
                company_files_pending(db),
                move_company_files(db),
                company_notes_to_move(db, other),
                move_company_notes(db, other),
            )
        finally:
            if is_async:
                await db.db_engine.dispose()

    # The migration runs to the end, and the other tables of the database are stamped.
    assert asyncio.run(migrate()) == (False, False, False, 0)
    with sqlite3.connect(path) as conn:
        assert sorted(conn.execute("SELECT namespace, path, content FROM agno_fs")) == sorted(rows_)
        stamped = dict(conn.execute("SELECT table_name, version FROM agno_schema_versions"))
    assert stamped and set(stamped.values()) == {"3.3.0"}
    other.db_engine.dispose()
    if not is_async:
        db.db_engine.dispose()


# ------------------------------------------------------------------ the same file at the new path


def test_the_same_content_at_the_new_path_keeps_the_higher_version(databases):
    db, reader = databases.new()
    # A page three writes old where 3.2.0 kept it, and the same content written once at its new path.
    used_by_company(reader)
    write_3_2_0(reader, "company/wiki", "people.md", "Ada", "Ada and Bo", "Ada, Bo and Cy")
    in_store(reader).write("wiki/people.md", "Ada, Bo and Cy")
    # The other way round: the new path was written more often than the old one.
    write_3_2_0(reader, "company/notes", "ideas.md", "An idea")
    for content in ("A draft", "Another", "An idea"):
        in_store(reader).write("notes/ideas.md", content)
    before = rows(reader)
    assert before[("company/wiki", "people.md")][1] == 3 and before[("company", "wiki/people.md")][1] == 1
    assert before[("company/notes", "ideas.md")][1] == 1 and before[("company", "notes/ideas.md")][1] == 3

    assert databases.run(move_company_files, amove_company_files, db) is True

    after = rows(reader)
    # The page keeps the version and the timestamps a client read before the upgrade.
    assert after == {
        ("company", "wiki/people.md"): before[("company/wiki", "people.md")],
        ("company", "notes/ideas.md"): before[("company", "notes/ideas.md")],
    }
    manager = CompanyManager(reader)
    assert manager.write_wiki(goal_id=None, path="people.md", content="Next", expected_version=3).version == 4


def test_a_note_moved_between_databases_keeps_the_higher_version(databases):
    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    for content in ("A note", "A better note", "The note"):
        in_store(os_reader).write("notes/ideas.md", content)
    in_store(company_reader).write("notes/ideas.md", "The note")
    source = rows(os_reader)[("company", "notes/ideas.md")]
    assert source[1] == 3 and rows(company_reader)[("company", "notes/ideas.md")][1] == 1

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1

    assert rows(company_reader) == {("company", "notes/ideas.md"): source} and rows(os_reader) == {}


# ------------------------------------------------------------------ two sets of Company tables in one database


def test_two_goal_tables_in_one_database_each_move_their_own_pages(databases):
    from agno.db.migrations.versions.v3_3_0 import acompany_files_left, company_files_left

    db, reader = databases.new()
    other_tables = {
        "goals_table": "other_goals",
        "projects_table": "other_projects",
        "tasks_table": "other_tasks",
        "sources_table": "other_sources",
    }
    where = {"db_file": reader.db_file} if databases.kind.endswith("sqlite") else {"db_url": reader.db_url}
    other_reader = type(reader)(**where, **other_tables)
    other_db = type(db)(**where, **other_tables)
    databases._opened.extend([(other_reader, False), (other_db, databases.is_async)])
    CompanyManager(reader).create(name="Launch", id="launch")
    other_manager = CompanyManager(other_reader)
    other_manager.create(name="Docs", id="Docs Team")
    project = other_manager.create_project(goal_id="Docs Team", name="Plan")
    other_task = other_manager.create_task(goal_id="Docs Team", title="Write", project_id=project["id"])
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    write_3_2_0(reader, "company/products/launch/wiki", "status.md", "Go")
    write_3_2_0(reader, "company/products/Docs Team/wiki", "status.md", "Drafting")
    write_3_2_0(reader, f"company/tasks/{other_task['id']}", "report.md", "The other report")
    before = rows(reader)
    docs, task = "company/products/docs%20team/wiki", f"company/tasks/{other_task['id'].lower()}"

    # The first set of tables moves its own Goal. The pages of a Goal it does not hold stay where they are.
    assert databases.run(move_company_files, amove_company_files, db) is True
    first = rows(reader)
    assert first[("company", "goals/launch/status.md")] == before[("company/products/launch/wiki", "status.md")]
    assert first[(docs, "status.md")] == before[(docs, "status.md")]
    assert first[(task, "report.md")] == before[(task, "report.md")]
    assert len(first) == len(before)
    assert databases.run(company_files_pending, acompany_files_pending, db) is False
    assert [entry["namespace"] for entry in databases.run(company_files_left, acompany_files_left, db)] == [docs, task]

    # The second set finds them waiting and moves them to the folders of its own records.
    assert databases.run(company_files_pending, acompany_files_pending, other_db) is True
    assert databases.run(move_company_files, amove_company_files, other_db) is True
    assert rows(reader) == {
        ("company", "goals/launch/status.md"): before[("company/products/launch/wiki", "status.md")],
        ("company", "goals/Docs%20Team/status.md"): before[(docs, "status.md")],
        ("company", f"tasks/{other_task['id']}/report.md"): before[(task, "report.md")],
    }
    assert other_manager.read_wiki("Docs Team", "status.md").content == "Drafting"


# ------------------------------------------------------------------ the size of the store after the move


@pytest.mark.parametrize("over", [True, False])
def test_the_migration_reports_a_store_that_ends_over_its_limit(databases, caplog, over):
    import logging

    from agno.company.filesystem import set_company_filesystem_bytes

    db, reader = databases.new()
    # Before 3.3.0 each folder had a limit of its own, so the folders together can hold more than one store may.
    used_by_company(reader)
    write_3_2_0(reader, "company/wiki", "people.md", "a" * 40)
    write_3_2_0(reader, "company/notes", "ideas.md", "b" * 40)
    in_store(reader).write("wiki/handbook.md", "c" * 20)
    set_company_filesystem_bytes(db, 90 if over else 100)
    before = rows(reader)

    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="agno"):
            assert databases.run(move_company_files, amove_company_files, db) is True
    finally:
        agno_logger.removeHandler(caplog.handler)

    # Every file moved either way: the limit refuses writes, never the migration.
    after = rows(reader)
    assert after[("company", "wiki/people.md")] == before[("company/wiki", "people.md")]
    assert after[("company", "notes/ideas.md")] == before[("company/notes", "ideas.md")]
    report = [record.getMessage() for record in caplog.records if "limit" in record.getMessage()]
    if over:
        assert len(report) == 1
        assert "100 bytes" in report[0] and "90 bytes" in report[0] and "max_filesystem_bytes" in report[0]
    else:
        assert report == []


def test_a_step_refused_because_another_connection_writes_is_tried_again(databases, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from agno.db.migrations.versions import v3_3_0

    os_db, os_reader = databases.new()
    company_db, company_reader = databases.new()
    in_store(os_reader).write("notes/ideas.md", "A note")
    before = rows(os_reader)
    monkeypatch.setattr(v3_3_0, "_BUSY_WAIT_SECONDS", 0)
    write = v3_3_0._write_notes
    calls: list = []

    def busy_twice(sess, db, notes) -> None:
        calls.append(len(notes))
        if len(calls) < 3:
            # What SQLite answers a writer while another connection writes.
            raise OperationalError("INSERT", {}, Exception("database is locked"))
        write(sess, db, notes)

    monkeypatch.setattr(v3_3_0, "_write_notes", busy_twice)

    assert databases.run(move_company_notes, amove_company_notes, os_db, company_db) == 1
    assert calls == [1, 1, 1]
    assert rows(company_reader) == before and rows(os_reader) == {}
    # Any other failure of the database is not tried again.
    in_store(os_reader).write("notes/more.md", "More")
    calls.clear()

    def broken(sess, db, notes) -> None:
        calls.append(len(notes))
        raise OperationalError("INSERT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(v3_3_0, "_write_notes", broken)
    with pytest.raises(OperationalError, match="disk I/O error"):
        databases.run(move_company_notes, amove_company_notes, os_db, company_db)
    assert calls == [1]
    assert ("company", "notes/more.md") in rows(os_reader)


# ------------------------------------------------------------------ what a run says, and two namespaces for one folder


def test_one_run_of_the_migration_reports_the_files_it_leaves_once(databases, caplog):
    import logging

    from agno.db.migrations.manager import MigrationManager

    db, reader = databases.new()
    CompanyManager(reader).create(name="Launch", id="launch")
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    write_3_2_0(reader, "company/products/gone/wiki", "status.md", "Of a Goal that was deleted")
    write_3_2_0(reader, "company/wiki", "people.md", "Ada")

    async def migrate() -> None:
        try:
            await MigrationManager(db).up()
        finally:
            if databases.is_async:
                await db.db_engine.dispose()

    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="agno"):
            asyncio.run(migrate())
            first = [r.getMessage() for r in caplog.records if "left where a version before" in r.getMessage()]
            # The manager runs the migration once for each Company table type. The report is made once.
            assert len(first) == 1 and "company/products/gone/wiki (status.md)" in first[0]
            assert ("company", "wiki/people.md") in rows(reader)
            # A later run that finds the same files left says nothing new.
            caplog.clear()
            assert databases.run(move_company_files, amove_company_files, db) is False
            assert not [r for r in caplog.records if "left where a version before" in r.getMessage()]
    finally:
        agno_logger.removeHandler(caplog.handler)


def test_two_namespaces_are_not_moved_into_one_folder_in_one_run(databases):
    db, reader = databases.new()
    manager = CompanyManager(reader)
    manager.create(name="Launch", id="launch")
    for meta in in_store(reader).list():
        in_store(reader).delete(meta.path)
    # The Goal's own pages wait, and an operator gives it the pages of a Goal that is gone, in the same run.
    write_3_2_0(reader, "company/products/launch/wiki", "status.md", "Go")
    write_3_2_0(reader, "company/products/gone/wiki", "status.md", "Of a Goal that was deleted")
    before = rows(reader)
    owners = {"company/products/gone/wiki": "launch"}

    def move():
        return databases.run(
            lambda d: move_company_files(d, owners=owners), lambda d: amove_company_files(d, owners=owners), db
        )

    with pytest.raises(CompanyFilesMigrationError, match="goals/launch"):
        move()
    assert rows(reader) == before
    # One at a time: the Goal's own pages first, then the others, where a page of the same name stops the move.
    assert databases.run(move_company_files, amove_company_files, db) is True
    with pytest.raises(CompanyFilesMigrationError, match="goals/launch/status.md"):
        move()
    after = rows(reader)
    assert after[("company", "goals/launch/status.md")] == before[("company/products/launch/wiki", "status.md")]
    assert after[("company/products/gone/wiki", "status.md")] == before[("company/products/gone/wiki", "status.md")]


@pytest.mark.parametrize("is_async", [False, True])
def test_a_postgres_role_that_cannot_read_the_cluster_identifier_still_tells_one_database_from_two(
    postgres_server, monkeypatch, is_async
):
    if not postgres_server:
        pytest.skip(f"Postgres server not reachable at {POSTGRES_URL}")
    from sqlalchemy.engine import make_url

    from agno.db.migrations.versions import v3_3_0
    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    # What a role without the right to call it gets: the statement fails.
    monkeypatch.setattr(v3_3_0, "_CLUSTER_ID", "SELECT system_identifier FROM pg_control_system_not_allowed()")
    databases = Databases("async-postgres" if is_async else "postgres", None)
    try:
        db, reader = databases.new()
        other_db, other_reader = databases.new()
        in_store(reader).write("notes/ideas.md", "A note")
        before = every_row(reader)
        by_address = make_url(db.db_url).set(host="127.0.0.1").render_as_string(hide_password=False)
        same = (AsyncPostgresDb if is_async else PostgresDb)(db_url=by_address)
        databases._opened.append((same, is_async))

        # One database under two host names is still one place, and another database is another.
        assert _run(is_async, company_notes_to_move, acompany_notes_to_move, db, same) is False
        assert _run(is_async, move_company_notes, amove_company_notes, db, same) == 0
        assert every_row(reader) == before
        assert _run(is_async, move_company_notes, amove_company_notes, db, other_db) == 1
        assert every_row(other_reader) == before and every_row(reader) == {}
    finally:
        databases.close()


# ------------------------------------------------------------------ the store, while files wait


def test_the_company_file_system_refuses_every_use_while_files_wait_and_serves_after_the_move(databases):
    from agno.company.filesystem import company_filesystem
    from agno.exceptions import MigrationRequiredError

    db, reader = databases.new()
    used_by_company(reader)
    write_3_2_0(reader, "company/wiki", "people.md", "Ada", "Ada and Bo")
    in_store(reader).write("notes/ideas.md", "A note")
    before = rows(reader)

    async def use(store, operation: str):
        try:
            if operation == "read":
                return await store.aread("wiki/people.md") if databases.is_async else store.read("wiki/people.md")
            if operation == "list":
                found = await store.alist() if databases.is_async else store.list()
                return sorted(meta.path for meta in found)
            if databases.is_async:
                return (await store.awrite("notes/new.md", "Written")).version
            return store.write("notes/new.md", "Written").version
        finally:
            if databases.is_async:
                await db.db_engine.dispose()

    # Reading, listing and writing are all refused, and nothing is written beside the page that waits.
    for operation in ("read", "list", "write"):
        with pytest.raises(MigrationRequiredError, match="databases/all/migrate"):
            asyncio.run(use(company_filesystem(db), operation))
    assert rows(reader) == before

    assert databases.run(move_company_files, amove_company_files, db) is True
    assert asyncio.run(use(company_filesystem(db), "read")) == "Ada and Bo"
    assert asyncio.run(use(company_filesystem(db), "list")) == ["notes/ideas.md", "wiki/people.md"]
    assert asyncio.run(use(company_filesystem(db), "write")) == 1
