"""Company is one file system: every file at its tree path, and what a Task run may write."""

import asyncio

import pytest

from agno.company.files import CompanyFiles
from agno.company.filesystem import (
    COMPANY_FILESYSTEM_BYTES,
    COMPANY_NAMESPACE,
    _Folder,
    company_filesystem,
    company_folder,
    folder_name,
)
from agno.company.manager import CompanyManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.fs import FileSystem
from agno.fs.errors import InvalidPathError, QuotaExceededError
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.session import TeamSession
from agno.tools.company_files import CompanyFileTools
from tests.unit.os.test_company_file_tree import call, pages, person, records, routine_run, task_run, tree
from tests.unit.os.test_mini_agent_tasks import ScriptedModel, System, headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")


@pytest.fixture
def system(tmp_path):
    value = System(tmp_path)
    yield value
    value.db.close()


def stored(db) -> dict:
    """Every file of the Company file system in a database, by its stored path."""
    store = company_filesystem(db)
    return {meta.path: store.read(meta.path) for meta in store.list()}


# ------------------------------------------------------------------ one store


@pytest.mark.parametrize("use_async", [False, True])
def test_every_file_is_stored_at_its_tree_path_in_one_namespace(system, use_async):
    ids = records(system)
    files = tree(system.os)
    goal_page, task_file = f"goals/{ids['goal']}/research.md", f"tasks/{ids['task']}/report.md"
    call(files, "write_company_file", use_async=use_async, path=goal_page, content="Research", expected_version=0)
    call(files, "write_company_file", use_async=use_async, path=task_file, content="Report")
    call(files, "write_company_file", use_async=use_async, path="notes/ideas.md", content="A note")
    CompanyManager(system.db).write_wiki(goal_id=None, path="people.md", content="Ada\n", expected_version=0)

    files_by_path = stored(system.db)
    assert files_by_path[goal_page] == "Research"
    assert files_by_path[task_file] == "Report"
    assert files_by_path["notes/ideas.md"] == "A note"
    assert files_by_path["wiki/people.md"] == "Ada\n"
    # Each top folder of the store is a folder of the tree, and nothing is stored outside the store.
    assert {path.split("/")[0] for path in files_by_path} == {"wiki", "goals", "tasks", "notes"}
    for namespace in (
        "company/wiki",
        "company/notes",
        f"company/products/{ids['goal']}/wiki",
        f"company/tasks/{ids['task']}",
    ):
        assert FileSystem(system.db, namespace=namespace, user_scoped=False).list() == [], namespace

    # The tree and the Company routes read the same files.
    read = call(files, "read_company_file", use_async=use_async, path=task_file)
    assert (read["path"], read["content"], read["version"]) == (task_file, "Report", 1)
    served = system.client.get(f"/company/goals/{ids['goal']}/wiki/research.md", headers=headers())
    assert served.status_code == 200 and served.json()["content"] == "Research"
    served = system.client.get(f"/company/tasks/{ids['task']}/files/report.md", headers=headers())
    assert served.status_code == 200 and served.json()["content"] == "Report"
    assert system.client.get("/company/notes/ideas.md", headers=headers()).json()["content"] == "A note"
    assert system.client.get("/company/wiki/people.md", headers=headers()).json()["content"] == "Ada\n"


@pytest.mark.parametrize("use_async", [False, True])
def test_a_path_written_on_3_2_0_under_products_names_the_goal_folder(system, use_async):
    ids = records(system)
    files = tree(system.os)
    page = f"goals/{ids['goal']}/research.md"
    call(files, "write_company_file", use_async=use_async, path=page, content="Research", expected_version=0)

    # A page, a brief or a note written on 3.2.0 names the folder as that version did.
    for old in (f"products/{ids['goal']}/research.md", f"company/products/{ids['goal']}/research.md"):
        read = call(files, "read_company_file", use_async=use_async, path=old)
        assert (read["path"], read["content"]) == (page, "Research")
    listed = call(files, "list_company_files", use_async=use_async, folder=f"products/{ids['goal']}")
    assert "research.md" in [entry["path"].rsplit("/", 1)[-1] for entry in listed["files"]]


def test_without_company_the_same_store_in_the_agentos_database_holds_notes_alone(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    agent_os = AgentOS(db=os_db, manager=OSManager(model=ScriptedModel()), telemetry=False)
    try:
        files = tree(agent_os)
        call(files, "write_company_file", path="notes/ideas.md", content="A note")

        assert stored(os_db) == {"notes/ideas.md": "A note"}
        assert call(files, "list_company_files")["folders"] == ["notes/"]
        with pytest.raises(ValueError, match="not available here"):
            call(files, "read_company_file", path="wiki/people.md")
    finally:
        os_db.close()


def test_one_limit_covers_the_whole_store(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    agent_os = AgentOS(
        db=db,
        manager=OSManager(model=ScriptedModel()),
        company=CompanyConfig(model=ScriptedModel(), max_filesystem_bytes=6_000),
        telemetry=False,
    )
    try:
        manager = CompanyManager(db, agent_os.registry)
        goal = manager.create(name="Launch")
        project = manager.create_project(goal_id=goal["id"], name="Plan")
        task = manager.create_task(goal_id=goal["id"], title="Write", project_id=project["id"])
        files = tree(agent_os)
        assert company_filesystem(db).max_namespace_bytes == 6_000

        call(files, "write_company_file", path="notes/big.md", content="n" * 4_000)
        # A Task's folder has no limit of its own: what the notes used counts against it.
        with pytest.raises(QuotaExceededError, match="storage is full"):
            call(files, "write_company_file", path=f"tasks/{task['id']}/report.md", content="r" * 4_000)
        with pytest.raises(QuotaExceededError, match="storage is full"):
            manager.write_wiki(goal_id=None, path="people.md", content="w" * 4_000, expected_version=0)
        assert (
            call(files, "write_company_file", path=f"tasks/{task['id']}/report.md", content="r" * 100)["version"] == 1
        )
    finally:
        db.close()


def test_the_limit_is_a_company_setting_with_a_default():
    assert CompanyConfig().max_filesystem_bytes == COMPANY_FILESYSTEM_BYTES == 1_000_000_000
    assert CompanyConfig(max_filesystem_bytes=5_000_000).max_filesystem_bytes == 5_000_000
    for refused in (0, -1, True, 1.5, "big"):
        with pytest.raises(ValueError, match="max_filesystem_bytes"):
            CompanyConfig(max_filesystem_bytes=refused)


def test_a_database_with_no_company_setting_uses_the_default_limit(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "plain.db"))
    try:
        assert company_filesystem(db).max_namespace_bytes == COMPANY_FILESYSTEM_BYTES
        assert company_folder(db, "notes").max_namespace_bytes == COMPANY_FILESYSTEM_BYTES
        assert company_filesystem(db).namespace == COMPANY_NAMESPACE
        assert company_filesystem(db).user_scoped is False
    finally:
        db.close()


# ------------------------------------------------------------------ files and notes that wait to be moved

MIGRATION_ERROR = "migration_required_error"


def _refused(response) -> str:
    """The message of a response that says a migration is pending."""
    assert response.status_code == 500, response.text
    assert response.json()["error_id"] == MIGRATION_ERROR, response.text
    return response.json()["detail"]


def _with_files_from_3_2_0(reader) -> dict:
    """Company records as this version stores them, and their files where 3.2.0 kept them."""
    from tests.unit.db.test_v3_3_0_company_files_migration import old_layout

    return old_layout(reader)


@pytest.mark.parametrize("two_databases", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_agentos_starts_with_files_waiting_and_company_refuses_them_until_they_move(tmp_path, two_databases, use_async):
    from fastapi.testclient import TestClient

    from agno.exceptions import MigrationRequiredError

    company_file = str(tmp_path / "company.db")
    reader = SqliteDb(db_file=company_file)
    ids = _with_files_from_3_2_0(reader)
    company_db = AsyncSqliteDb(db_file=company_file) if use_async else SqliteDb(db_file=company_file)
    if two_databases:
        os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
        agent_os = AgentOS(db=os_db, company=CompanyConfig(db=company_db), telemetry=False)
    else:
        os_db = company_db
        agent_os = AgentOS(db=company_db, company=CompanyConfig(), telemetry=False)
    urls = {
        "/company/wiki/brief.md": "# Company\n\nWe ship weekly.\n",
        f"/company/goals/{ids['goal']}/wiki/research/notes.md": "three",
        f"/company/tasks/{ids['task']}/files/report.md": "The report",
        "/company/notes/ideas.md": "A better note",
    }

    # AgentOS starts. The Company file system serves no file while files wait where 3.2.0 kept them.
    with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
        for url in urls:
            message = _refused(client.get(url))
            assert "MigrationManager(db).up()" in message and "POST /databases/all/migrate" in message
        assert _refused(client.get("/company/wiki")) and _refused(client.get("/company/notes"))
        # A tool is refused with the same error, and nothing is written beside the files that wait.
        files = CompanyFileTools(company_db, notes_db=company_db)
        for name, arguments in (
            ("read_company_file", {"path": "wiki/brief.md"}),
            ("list_company_files", {"folder": "notes"}),
            ("write_company_file", {"path": "notes/new.md", "content": "Written before the move"}),
        ):
            with pytest.raises(MigrationRequiredError, match="databases/all/migrate"):
                call(files, name, None, use_async, **arguments)
        # Records are not files: they are served.
        assert client.get(f"/company/goals/{ids['goal']}").status_code == 200

        # The route the error names moves the files, and the same AgentOS serves them without a restart.
        migrated = client.post("/databases/all/migrate")
        assert migrated.status_code == 200, migrated.text
        for url, content in urls.items():
            served = client.get(url)
            assert served.status_code == 200, (url, served.text)
            assert served.json()["content"] == content
        assert call(files, "read_company_file", None, use_async, path="wiki/brief.md")["version"] == 2
    for db in {reader, os_db, company_db}:
        if not isinstance(db, AsyncSqliteDb):
            db.close()


@pytest.mark.parametrize("use_async", [False, True])
def test_super_agent_without_company_does_not_read_or_write_notes_past_the_ones_that_wait(tmp_path, use_async):
    from agno.db.migrations.manager import MigrationManager
    from agno.exceptions import MigrationRequiredError

    db_file = str(tmp_path / "agentos.db")
    reader = SqliteDb(db_file=db_file)
    # An AgentOS without Company on 3.2.0: Super Agent's notes, where that version kept them.
    FileSystem(reader, namespace="company/notes", user_scoped=False).write("ideas.md", "A note from 3.2.0")
    reader.upsert_session(TeamSession(session_id="chat", team_id="superagent", created_at=1))
    # Super Agent needs a synchronous AgentOS database. Its tools are called both ways.
    db = SqliteDb(db_file=db_file)
    agent_os = AgentOS(db=db, manager=OSManager(model=ScriptedModel()), telemetry=False)
    files = tree(agent_os)

    # The notes are not served as an empty folder, and no note is written beside them.
    for name, arguments in (
        ("list_company_files", {"folder": "notes"}),
        ("read_company_file", {"path": "notes/ideas.md"}),
        ("write_company_file", {"path": "notes/ideas.md", "content": "Written on this version"}),
    ):
        with pytest.raises(MigrationRequiredError, match=r"MigrationManager\(db\)\.up\(\)"):
            call(files, name, None, use_async, **arguments)

    # The migration then moves the note: nothing was written in its way.
    asyncio.run(MigrationManager(db).up())
    assert call(files, "read_company_file", None, use_async, path="notes/ideas.md")["content"] == "A note from 3.2.0"
    reader.close()


def _statements(db, seen: list, label: str) -> None:
    from sqlalchemy import event

    @event.listens_for(db.db_engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append((label, " ".join(statement.split())))


def _notes_left_in_the_agentos_database(tmp_path, where: str) -> tuple:
    """Notes written before 3.3.0 in the AgentOS database, and a Company database kept apart from it."""
    os_file, company_file = str(tmp_path / "os.db"), str(tmp_path / "company.db")
    os_reader, company_db = SqliteDb(db_file=os_file), SqliteDb(db_file=company_file)
    # Where 3.2.0 kept them, or where the migration of the AgentOS database put them.
    if where == "company/notes":
        FileSystem(os_reader, namespace="company/notes", user_scoped=False).write("ideas.md", "A note")
    else:
        FileSystem(os_reader, namespace="company", user_scoped=False).write("notes/ideas.md", "A note")
    FileSystem(company_db, namespace="company", user_scoped=False).write("wiki/people.md", "Ada")
    return os_file, os_reader, company_db


@pytest.mark.parametrize("where", ["company/notes", "company"])
@pytest.mark.parametrize("os_async", [False, True])
def test_the_migrate_route_moves_notes_left_in_the_agentos_database(tmp_path, where, os_async):
    from fastapi.testclient import TestClient

    os_file, os_reader, company_db = _notes_left_in_the_agentos_database(tmp_path, where)
    seen: list = []
    _statements(os_reader, seen, "os")

    def start() -> AgentOS:
        os_db = AsyncSqliteDb(db_file=os_file) if os_async else os_reader
        return AgentOS(db=os_db, company=CompanyConfig(db=company_db), telemetry=False)

    with TestClient(start().get_app(), raise_server_exceptions=False) as client:
        # The start moves nothing: the note is where it was, and notes/ says what to run.
        assert "move_company_notes" in _refused(client.get("/company/notes/ideas.md"))
        assert "notes/ideas.md" not in stored(company_db)
        assert client.post("/databases/all/migrate").status_code == 200
        served = client.get("/company/notes/ideas.md")
        assert served.status_code == 200 and served.json()["content"] == "A note"
        assert [row["path"] for row in client.get("/company/notes").json()["data"]] == ["ideas.md"]
    # The note left the AgentOS database: it is in one place.
    assert stored(company_db) == {"notes/ideas.md": "A note", "wiki/people.md": "Ada"}
    assert FileSystem(os_reader, namespace="company", user_scoped=False).list() == []
    assert FileSystem(os_reader, namespace="company/notes", user_scoped=False).list() == []

    # A second start moves nothing and writes nothing to the file table.
    with TestClient(start().get_app()) as client:
        assert client.get("/company/notes/ideas.md").json()["content"] == "A note"
    assert stored(company_db) == {"notes/ideas.md": "A note", "wiki/people.md": "Ada"}
    os_reader.close()
    company_db.close()


@pytest.mark.parametrize("reason", ["provisioning is off", "another note is in the way"])
@pytest.mark.parametrize("os_async", [False, True])
def test_notes_left_in_the_agentos_database_are_refused_until_they_move(tmp_path, reason, os_async):
    import logging

    from fastapi.testclient import TestClient

    from agno.db.migrations.versions.v3_3_0 import move_company_notes

    os_file, os_reader, company_db = _notes_left_in_the_agentos_database(tmp_path, "company/notes")
    in_the_way = FileSystem(company_db, namespace="company", user_scoped=False)
    if reason == "another note is in the way":
        in_the_way.write("notes/ideas.md", "Written on this version")
    os_db = AsyncSqliteDb(db_file=os_file) if os_async else SqliteDb(db_file=os_file)
    agent_os = AgentOS(
        db=os_db,
        company=CompanyConfig(db=company_db),
        auto_provision_dbs=reason != "provisioning is off",
        telemetry=False,
    )
    errors: list = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            errors.append(record.getMessage())

    handler = Collect(level=logging.ERROR)
    # agno logs through one of three loggers, and an earlier test can leave any of them active.
    loggers = [logging.getLogger(name) for name in ("agno", "agno-team", "agno-workflow")]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        # AgentOS starts either way. Only notes/ waits: the rest of the Company file system is served.
        with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
            assert client.get("/company/wiki/people.md").json()["content"] == "Ada"
            for url in ("/company/notes", "/company/notes/ideas.md"):
                message = _refused(client.get(url))
                assert "move_company_notes" in message and "agno.db.migrations.versions.v3_3_0" in message
                assert "amove_company_notes" in message
            # The start did not try to move them.
            assert [message for message in errors if "Notes were not moved" in message] == []
            if reason == "another note is in the way":
                # The migrate route says once why it moved nothing, and notes/ stays refused.
                assert client.post("/databases/all/migrate").status_code == 200
                not_moved = [message for message in errors if "Notes were not moved" in message]
                assert len(not_moved) == 1 and "notes/ideas.md" in not_moved[0]
                assert "move_company_notes" in _refused(client.get("/company/notes/ideas.md"))
                in_the_way.delete("notes/ideas.md")
            # The call the error names is the whole remedy, and the same AgentOS then serves the note.
            assert move_company_notes(os_reader, company_db) == 1
            served = client.get("/company/notes/ideas.md")
            assert served.status_code == 200 and served.json()["content"] == "A note"
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
    os_reader.close()
    company_db.close()
    if not os_async:
        os_db.close()


def test_notes_left_behind_are_refused_through_the_synchronous_tree_too(tmp_path):
    from agno.company.filesystem import set_company_notes_source
    from agno.db.migrations.versions.v3_3_0 import move_company_notes
    from agno.exceptions import MigrationRequiredError

    os_db, company_db = SqliteDb(db_file=str(tmp_path / "os.db")), SqliteDb(db_file=str(tmp_path / "company.db"))
    FileSystem(os_db, namespace="company/notes", user_scoped=False).write("ideas.md", "A note")
    set_company_notes_source(company_db, os_db)
    files = CompanyFiles(company_db, notes_db=company_db)
    for use in (lambda: files.read("notes/ideas.md"), lambda: files.write("notes/new.md", "Not written")):
        with pytest.raises(MigrationRequiredError, match="move_company_notes"):
            use()
    assert stored(company_db) == {}
    assert move_company_notes(os_db, company_db) == 1
    assert files.read("notes/ideas.md")["content"] == "A note"

    # A synchronous use cannot ask an asynchronous AgentOS database, so it refuses until an asynchronous
    # check finds nothing waiting.
    later_file = str(tmp_path / "later.db")
    FileSystem(SqliteDb(db_file=later_file), namespace="company/notes", user_scoped=False).write("ideas.md", "A note")
    later_os, later_company = AsyncSqliteDb(db_file=later_file), SqliteDb(db_file=str(tmp_path / "later-company.db"))
    set_company_notes_source(later_company, later_os)
    later = CompanyFiles(later_company, notes_db=later_company)
    for use in (lambda: later.list("notes"), lambda: later.write("notes/new.md", "Not written")):
        with pytest.raises(MigrationRequiredError, match="amove_company_notes"):
            use()
    assert stored(later_company) == {}

    async def move_and_check() -> None:
        from agno.db.migrations.versions.v3_3_0 import amove_company_notes

        try:
            with pytest.raises(MigrationRequiredError, match="move_company_notes"):
                await later.alist("notes")
            assert await amove_company_notes(later_os, later_company) == 1
            await later.alist("notes")
        finally:
            await later_os.db_engine.dispose()

    asyncio.run(move_and_check())
    assert later.read("notes/ideas.md")["content"] == "A note"
    for db in (os_db, company_db, later_company):
        db.close()


def test_agentos_serves_notes_when_none_is_left_behind(tmp_path):
    from fastapi.testclient import TestClient

    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    company_db = SqliteDb(db_file=str(tmp_path / "company.db"))
    # Other files in the AgentOS database are not notes, and notes in the Company database are in place.
    FileSystem(os_db, namespace="default", user_scoped=False).write("keep.md", "An agent's file")
    plain = FileSystem(os_db, namespace="company", user_scoped=False)
    plain.write("agents/keep.md", "Not under notes/")
    # A folder whose name differs from notes/ only by case is another folder.
    plain.write("Notes/shout.md", "Not the notes folder")
    company_filesystem(company_db).write("notes/ideas.md", "A note")
    with TestClient(AgentOS(db=os_db, company=CompanyConfig(db=company_db), telemetry=False).get_app()) as client:
        assert client.get("/company/notes/ideas.md").json()["content"] == "A note"

    # One database for both: the notes in the AgentOS database are where they belong.
    single = SqliteDb(db_file=str(tmp_path / "single.db"))
    company_filesystem(single).write("notes/ideas.md", "A note")
    with TestClient(AgentOS(db=single, company=CompanyConfig(), telemetry=False).get_app()) as client:
        assert client.get("/company/notes/ideas.md").json()["content"] == "A note"
    twin = SqliteDb(db_file=str(tmp_path / "single.db"))
    with TestClient(AgentOS(db=single, company=CompanyConfig(db=twin), telemetry=False).get_app()) as client:
        assert client.get("/company/notes/ideas.md").json()["content"] == "A note"
    for db in (os_db, company_db, single, twin):
        db.close()


def test_the_check_for_waiting_files_runs_at_first_use_and_stops_once_nothing_waits(tmp_path):
    import logging

    from fastapi.testclient import TestClient

    seen: list = []
    logged: list = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logged.append(record.getMessage())

    def looked_for_waiting_files(statements: list) -> list:
        return [label for label, statement in statements if statement.startswith("SELECT DISTINCT agno_fs.namespace")]

    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    plain = FileSystem(db, namespace="company", user_scoped=False)
    plain.write("wiki/brief.md", "# Company")
    FileSystem(db, namespace="default", user_scoped=False).write("keep.md", "An agent's file")
    _statements(db, seen, "db")
    agent_os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)

    handler = Collect(level=logging.DEBUG)
    logger = logging.getLogger("agno")
    level = logger.level
    try:
        with TestClient(agent_os.get_app()) as client:
            # Starting AgentOS does not look at the file table for files that wait.
            assert looked_for_waiting_files(seen) == []
            seen.clear()
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            # The first use looks once. After that nothing waits, and no later use looks again.
            assert client.get("/company/wiki/brief.md").json()["content"] == "# Company"
            assert looked_for_waiting_files(seen) == ["db"]
            assert [message for message in logged if "wait" in message or "moved" in message] == []
            seen.clear()
            assert client.get("/company/wiki/brief.md").status_code == 200
            assert client.get("/company/notes").status_code == 200
            assert company_filesystem(db).read("wiki/brief.md") == "# Company"
            assert looked_for_waiting_files(seen) == []
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    db.close()


# ------------------------------------------------------------------ what a Task run may write


def _escapes(ids) -> list:
    """Paths a Task run on ids['task'] of ids['goal'] must not write, with why each one is tried."""
    own_task, own_goal, other_task, other_goal = ids["task"], ids["goal"], ids["stray"], ids["other"]
    return [
        # Another Task's folder, another Goal's folder, the wiki, and the brief of its own Goal.
        f"tasks/{other_task}/report.md",
        f"goals/{other_goal}/research.md",
        "wiki/people.md",
        f"goals/{own_goal}/brief.md",
        f"goals/{other_goal}/brief.md",
        # Notes are Super Agent's.
        "notes/ideas.md",
        # '..' out of its own folders.
        f"tasks/{own_task}/../{other_task}/report.md",
        f"tasks/{own_task}/../../wiki/people.md",
        f"goals/{own_goal}/../{other_goal}/research.md",
        f"goals/{own_goal}/../../notes/ideas.md",
        f"tasks/{own_task}/./../{other_task}/report.md",
        f"tasks/{own_task}/a/../../{other_task}/report.md",
        # A doubled slash, a leading slash and the company/ prefix all name the same folders.
        f"tasks//{other_task}/report.md",
        f"//tasks/{other_task}/report.md",
        f"/goals/{other_goal}/research.md",
        f"company/tasks/{other_task}/report.md",
        "company//wiki/people.md",
        f"tasks/{own_task}//../{other_task}/report.md",
        # A folder name that starts like its own, and one that differs only by case.
        f"tasks/{own_task}x/report.md",
        f"tasks/{own_task.upper()}X/report.md",
        f"goals/{own_goal}-other/research.md",
        # Backslashes and control characters do not separate folders.
        f"tasks/{own_task}\\..\\{other_task}\\report.md",
        f"tasks/{own_task}/..\x00/{other_task}/report.md",
        f"tasks/{own_task}/\n../{other_task}/report.md",
        # Its own folder with no file named, and the top of the tree.
        f"tasks/{own_task}",
        f"tasks/{own_task}/",
        "tasks",
        "",
    ]


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_writes_only_under_its_own_task_and_its_own_goal(system, use_async):
    ids = records(system)
    files = tree(system.os)
    run = task_run(ids["goal"], ids["task"])
    own_file, own_page = f"tasks/{ids['task']}/report.md", f"goals/{ids['goal']}/research.md"

    assert call(files, "write_company_file", run, use_async, path=own_file, content="The report")["version"] == 1
    written = call(files, "write_company_file", run, use_async, path=own_page, content="Found", expected_version=0)
    assert written["version"] == 1
    # A deeper path in its own folder is its own too.
    deep = f"tasks/{ids['task']}/drafts/v1/notes.md"
    assert call(files, "write_company_file", run, use_async, path=deep, content="Draft")["path"] == deep

    before = pages(system, ids)
    assert before[own_file] == "The report" and before[own_page] == "Found" and before[deep] == "Draft"
    for path in _escapes(ids):
        with pytest.raises((PermissionError, ValueError, LookupError, InvalidPathError)) as refused:
            call(files, "write_company_file", run, use_async, path=path, content="Escaped", expected_version=0)
        assert not isinstance(refused.value, QuotaExceededError), path
        # Nothing was written anywhere in the store.
        assert pages(system, ids) == before, path
    assert "Escaped" not in "".join(stored(system.db).values())


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_is_told_which_folders_are_its_own(system, use_async):
    ids = records(system)
    files = tree(system.os)
    run = task_run(ids["goal"], ids["task"])

    # A doubled or leading slash names the same folder, and is refused as that folder is.
    for path in (
        f"tasks/{ids['stray']}/report.md",
        f"goals/{ids['other']}/research.md",
        f"//tasks/{ids['stray']}/report.md",
        f"/goals//{ids['other']}/research.md",
    ):
        with pytest.raises(PermissionError, match="only under its own Goal and in its own Task folder"):
            call(files, "write_company_file", run, use_async, path=path, content="x", expected_version=0)
    for path in ("wiki/people.md", f"goals/{ids['goal']}/brief.md"):
        with pytest.raises(PermissionError, match="only a person changes them"):
            call(files, "write_company_file", run, use_async, path=path, content="x", expected_version=0)
    with pytest.raises(PermissionError, match="only under its own Goal and in its own Task folder"):
        call(files, "write_company_file", run, use_async, path="notes/ideas.md", content="x")
    # Reading shows the same: the tree a Task run sees has no notes/.
    with pytest.raises(ValueError, match="notes/ is not available here"):
        call(files, "read_company_file", run, use_async, path="notes/ideas.md")
    for path in (f"tasks/{ids['task']}/../{ids['stray']}/report.md", f"tasks/{ids['task']}\\report.md"):
        with pytest.raises(InvalidPathError):
            call(files, "write_company_file", run, use_async, path=path, content="x")


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_with_no_goal_or_no_task_writes_nowhere(system, use_async):
    ids = records(system)
    files = tree(system.os)
    before = pages(system, ids)

    no_goal = task_run(None, ids["task"])
    with pytest.raises(PermissionError):
        call(
            files,
            "write_company_file",
            no_goal,
            use_async,
            path=f"goals/{ids['goal']}/research.md",
            content="x",
            expected_version=0,
        )
    no_task = task_run(ids["goal"], None)
    with pytest.raises(PermissionError):
        call(files, "write_company_file", no_task, use_async, path=f"tasks/{ids['task']}/report.md", content="x")
    assert pages(system, ids) == before


@pytest.mark.parametrize("use_async", [False, True])
def test_a_routine_run_writes_no_file_in_the_store(system, use_async):
    ids = records(system)
    files = tree(system.os)
    before = pages(system, ids)

    for path in (f"goals/{ids['goal']}/research.md", f"tasks/{ids['task']}/report.md", "notes/ideas.md"):
        with pytest.raises((PermissionError, ValueError)):
            call(
                files,
                "write_company_file",
                routine_run(ids["goal"]),
                use_async,
                path=path,
                content="x",
                expected_version=0,
            )
    assert pages(system, ids) == before


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_cannot_delete_or_save_a_page_outside_its_folders(system, use_async):
    ids = records(system)
    files = tree(system.os)
    call(files, "write_company_file", person(), use_async, path="notes/ideas.md", content="A note")
    run = task_run(ids["goal"], ids["task"])
    before = pages(system, ids)

    with pytest.raises((PermissionError, ValueError)):
        call(files, "delete_company_file", run, use_async, path="notes/ideas.md")
    with pytest.raises(InvalidPathError):
        call(files, "delete_company_file", run, use_async, path=f"tasks/{ids['task']}/../../notes/ideas.md")
    with pytest.raises((PermissionError, ValueError)):
        call(files, "save_company_page", run, use_async, path="wiki/people.md", expected_version=0, new_text="Mallory")
    assert pages(system, ids) == before


@pytest.mark.parametrize("use_async", [False, True])
def test_only_a_note_can_be_deleted_whoever_asks(system, use_async):
    ids = records(system)
    files = tree(system.os)
    task_file, goal_page = f"tasks/{ids['task']}/report.md", f"goals/{ids['goal']}/research.md"
    call(files, "write_company_file", use_async=use_async, path=task_file, content="The report")
    call(files, "write_company_file", use_async=use_async, path=goal_page, content="Found", expected_version=0)
    call(files, "write_company_file", use_async=use_async, path="notes/ideas.md", content="A note")
    before = pages(system, ids)

    for authority in (None, person(), task_run(ids["goal"], ids["task"])):
        for path in (task_file, goal_page, f"goals/{ids['goal']}/brief.md", "wiki/brief.md"):
            with pytest.raises((PermissionError, ValueError)):
                call(files, "delete_company_file", authority, use_async, path=path)
    assert pages(system, ids) == before

    assert call(files, "delete_company_file", person(), use_async, path="notes/ideas.md")["deleted"] is True
    assert "notes/ideas.md" not in pages(system, ids)


@pytest.mark.parametrize("use_async", [False, True])
def test_a_stale_version_is_refused_in_the_one_store(system, use_async):
    ids = records(system)
    files = tree(system.os)
    page = f"goals/{ids['goal']}/research.md"
    call(files, "write_company_file", use_async=use_async, path=page, content="First", expected_version=0)
    call(files, "write_company_file", use_async=use_async, path=page, content="Second", expected_version=1)

    from agno.fs.errors import VersionConflictError

    with pytest.raises(VersionConflictError):
        call(files, "write_company_file", use_async=use_async, path=page, content="Late", expected_version=1)
    with pytest.raises(VersionConflictError):
        call(files, "write_company_file", use_async=use_async, path=page, content="Again", expected_version=0)
    assert stored(system.db)[page] == "Second"
    # A file of the same name in another folder has its own version.
    other = f"goals/{ids['other']}/research.md"
    assert call(files, "write_company_file", use_async=use_async, path=other, content="Theirs", expected_version=0)[
        "version"
    ] == (1)


# ------------------------------------------------------------------ one folder of the store


@pytest.fixture
def db(tmp_path):
    database = SqliteDb(db_file=str(tmp_path / "folders.db"))
    yield database
    database.close()


def test_a_folder_reads_and_writes_only_inside_itself(db):
    whole = company_filesystem(db)
    whole.write("tasks/t1/report.md", "one needle")
    whole.write("tasks/t10/report.md", "ten needle")
    whole.write("tasks/t1x/report.md", "x needle")
    whole.write("wiki/people.md", "wiki needle")
    folder = company_folder(db, "tasks/t1")

    assert [meta.path for meta in folder.list()] == ["report.md"]
    assert folder.read("report.md") == "one needle"
    assert folder.read_with_meta("report.md").metadata.path == "report.md"
    assert [match.path for match in folder.search("needle")] == ["report.md"]
    assert folder.contains(["one needle", "ten needle"]).found == ["one needle"]
    assert folder.read("people.md") is None

    assert folder.write("drafts/a.md", "draft").path == "drafts/a.md"
    assert folder.append("log.md", "line").path == "log.md"
    assert folder.move("drafts/a.md", "final.md").path == "final.md"
    assert folder.delete("log.md") is True
    assert sorted(meta.path for meta in whole.list("tasks")) == [
        "tasks/t1/final.md",
        "tasks/t1/report.md",
        "tasks/t10/report.md",
        "tasks/t1x/report.md",
    ]
    assert [meta.path for meta in folder.list("drafts")] == []
    # The folder's size is the size of the whole store.
    assert folder.usage() == whole.usage()


@pytest.mark.parametrize(
    "path",
    ["../t10/report.md", "../../wiki/people.md", "a/../../t10/report.md", "/report.md", "a//b.md", "./report.md", ""],
)
def test_a_folder_refuses_a_path_that_is_not_a_plain_path_inside_it(db, path):
    whole = company_filesystem(db)
    whole.write("tasks/t10/report.md", "ten")
    whole.write("wiki/people.md", "wiki")
    backend = _Folder(whole.backend, "tasks/t1")
    before = {meta.path: whole.read(meta.path) for meta in whole.list()}

    # The backend is called directly: no caller above it has normalized the path.
    for attempt in (
        lambda: backend.read(COMPANY_NAMESPACE, path),
        lambda: backend.read_with_meta(COMPANY_NAMESPACE, path),
        lambda: backend.write(COMPANY_NAMESPACE, path, "Escaped"),
        lambda: backend.append(COMPANY_NAMESPACE, path, "Escaped"),
        lambda: backend.delete(COMPANY_NAMESPACE, path),
        lambda: backend.move(COMPANY_NAMESPACE, "report.md", path),
        lambda: backend.move(COMPANY_NAMESPACE, path, "report.md"),
        lambda: backend._stat(COMPANY_NAMESPACE, path),
        lambda: asyncio.run(backend.aread(COMPANY_NAMESPACE, path)),
        lambda: asyncio.run(backend.awrite(COMPANY_NAMESPACE, path, "Escaped")),
        lambda: asyncio.run(backend.adelete(COMPANY_NAMESPACE, path)),
        lambda: asyncio.run(backend.amove(COMPANY_NAMESPACE, "report.md", path)),
    ):
        with pytest.raises(InvalidPathError):
            attempt()
    if path:
        # A folder to list or search is held to the same rule; the empty path is the folder itself.
        for attempt in (
            lambda: backend.list(COMPANY_NAMESPACE, path),
            lambda: backend.search(COMPANY_NAMESPACE, "ten", path),
            lambda: backend.contains(COMPANY_NAMESPACE, ["ten"], path),
            lambda: asyncio.run(backend.alist(COMPANY_NAMESPACE, path)),
            lambda: asyncio.run(backend.asearch(COMPANY_NAMESPACE, "ten", path)),
        ):
            with pytest.raises(InvalidPathError):
                attempt()
    assert {meta.path: whole.read(meta.path) for meta in whole.list()} == before


@pytest.mark.parametrize("use_async", [False, True])
def test_an_error_from_a_folder_names_the_path_inside_the_folder(tmp_path, use_async):
    from agno.fs.errors import VersionConflictError

    db = (AsyncSqliteDb if use_async else SqliteDb)(db_file=str(tmp_path / "errors.db"))
    folder = company_folder(db, "goals/launch")

    async def act(name, *args, **kwargs):
        result = getattr(folder, ("a" if use_async else "") + name)(*args, **kwargs)
        return await result if use_async else result

    async def run() -> None:
        await act("write", "status.md", "one", expected_version=0)
        # The text a caller matches on is the text an unwrapped store gives for the same path.
        with pytest.raises(VersionConflictError) as stale:
            await act("write", "status.md", "late", expected_version=7)
        assert str(stale.value) == "version conflict on status.md: expected 7, actual 1"
        assert (stale.value.expected, stale.value.actual) == (7, 1)
        with pytest.raises(VersionConflictError) as exists:
            await act("write", "status.md", "again", expected_version=0)
        assert str(exists.value) == "file already exists: status.md"
        with pytest.raises(FileNotFoundError) as missing:
            await act("move", "gone.md", "there.md")
        assert str(missing.value) == "file not found: gone.md"
        await act("write", "other.md", "two")
        with pytest.raises(FileExistsError) as taken:
            await act("move", "other.md", "status.md")
        assert str(taken.value) == "file exists: status.md"
        if use_async:
            await db.close()
        else:
            db.close()

    asyncio.run(run())


def test_a_folder_name_is_matched_exactly(db):
    whole = company_filesystem(db)
    # Names that a pattern match or a match without case would take for tasks/t_1.
    for name in ("t_1", "tx1", "T_1", "t_1x", "t%1", "t_1/sub"):
        whole.write(f"tasks/{name}/report.md", f"in {name}")

    folder = company_folder(db, "tasks/t_1")
    assert sorted(meta.path for meta in folder.list()) == ["report.md", "sub/report.md"]
    assert folder.read("report.md") == "in t_1"
    assert sorted(match.path for match in folder.search("in t")) == ["report.md", "sub/report.md"]
    assert [meta.path for meta in company_folder(db, "tasks/t%1").list()] == ["report.md"]
    assert [meta.path for meta in company_folder(db, "tasks/T_1").list()] == ["report.md"]
    assert company_folder(db, "tasks/T_1").read("report.md") == "in T_1"


def test_a_folder_works_on_an_asynchronous_database(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))

    async def run() -> None:
        whole = company_filesystem(db)
        folder = company_folder(db, "goals/launch")
        await whole.awrite("goals/launch-2/brief.md", "other needle")
        assert (await folder.awrite("brief.md", "own needle", expected_version=0)).path == "brief.md"
        assert await folder.aread("brief.md") == "own needle"
        assert (await folder.aread_with_meta("brief.md")).metadata.version == 1
        assert [meta.path for meta in await folder.alist()] == ["brief.md"]
        assert [match.path for match in await folder.asearch("needle")] == ["brief.md"]
        assert (await folder.aappend("log.md", "line")).path == "log.md"
        assert (await folder.amove("log.md", "moved.md")).path == "moved.md"
        assert await folder.adelete("moved.md") is True
        assert (await folder.acontains(["own needle", "other needle"])).found == ["own needle"]
        assert sorted(meta.path for meta in await whole.alist()) == ["goals/launch-2/brief.md", "goals/launch/brief.md"]
        assert await folder.ausage() == await whole.ausage()
        await db.close()

    asyncio.run(run())


def test_the_tree_opens_each_area_as_a_folder_of_the_store(db):
    files = CompanyFiles(db, notes_db=db)
    manager = CompanyManager(db)
    goal = manager.create(name="Launch")

    files.write("notes/ideas.md", "A note")
    files.write(f"goals/{goal['id']}/research.md", "Research", expected_version=0)

    assert stored(db)["notes/ideas.md"] == "A note"
    assert stored(db)[f"goals/{goal['id']}/research.md"] == "Research"
    # The wiki of a Goal lists that Goal's folder alone.
    listed = [row.path for row in manager.list_wiki(goal["id"], limit=100)[0]]
    assert sorted(listed) == ["brief.md", "research.md", "status.md"]
    assert [row.path for row in manager.list_wiki(None, limit=100)[0]] == ["brief.md", "status.md"]


# ------------------------------------------------------------------ one folder of the store, on PostgreSQL

POSTGRES_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


@pytest.fixture
def postgres_url():
    """A PostgreSQL database of its own for one test: the Company store is one namespace of a database's file table.

    Uses the live pgvector container (localhost:5532) and skips when psycopg or the server is absent.
    """
    pytest.importorskip("psycopg")
    from uuid import uuid4

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    name = "company_folders_" + uuid4().hex[:12]
    admin = create_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception:
        admin.dispose()
        pytest.skip(f"Postgres server not reachable at {POSTGRES_URL}")
    try:
        yield make_url(POSTGRES_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.parametrize("use_async", [False, True])
def test_a_folder_reaches_no_other_folder_on_postgres(postgres_url, use_async):
    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    async def run() -> None:
        db = (AsyncPostgresDb if use_async else PostgresDb)(db_url=postgres_url)
        whole = company_filesystem(db)

        async def act(store, name, *args, **kwargs):
            result = getattr(store, ("a" if use_async else "") + name)(*args, **kwargs)
            return await result if use_async else result

        # Names that a pattern match or a match without case would take for tasks/t_1.
        for name in ("t_1", "tx1", "T_1", "t_1x", "t%1", "t_1/sub"):
            await act(whole, "write", f"tasks/{name}/report.md", f"in {name}")
        folder = company_folder(db, "tasks/t_1")

        assert sorted(meta.path for meta in await act(folder, "list")) == ["report.md", "sub/report.md"]
        assert await act(folder, "read", "report.md") == "in t_1"
        assert sorted(match.path for match in await act(folder, "search", "in t")) == ["report.md", "sub/report.md"]
        assert [meta.path for meta in await act(company_folder(db, "tasks/t%1"), "list")] == ["report.md"]
        assert await act(company_folder(db, "tasks/T_1"), "read", "report.md") == "in T_1"
        # A write and a version check stay inside the folder, and an error names the path inside it.
        from agno.fs.errors import VersionConflictError

        assert (await act(folder, "write", "status.md", "one", expected_version=0)).path == "status.md"
        with pytest.raises(VersionConflictError) as stale:
            await act(folder, "write", "status.md", "late", expected_version=7)
        assert str(stale.value) == "version conflict on status.md: expected 7, actual 1"
        assert await act(whole, "read", "tasks/t_1/status.md") == "one"
        assert await act(company_folder(db, "tasks/tx1"), "read", "status.md") is None
        with pytest.raises(InvalidPathError):
            await act(folder, "write", "../tx1/report.md", "Escaped")
        assert await act(whole, "read", "tasks/tx1/report.md") == "in tx1"
        if use_async:
            await db.close()
        else:
            db.close()

    asyncio.run(run())


# ------------------------------------------------------------------ the folder of an id


def test_a_folder_name_is_one_path_segment_and_keeps_ids_apart():
    from agno.company.filesystem import folder_name
    from agno.fs._paths import normalize_path

    ids = [
        "launch", "Launch", "LAUNCH", "docs team", "docs%20team", "docs+team", "team", "team/growth", "team%2fgrowth",
        "/team", "team/", "a//b", "a/b", ".", "..", "...", "%2e", "%2e.", "café", "café", "a\\b", "a\tb",
        "x{user_id}", "50%off", "me@example.com", " ", "  ", "名前",
    ]  # fmt: skip
    names = [folder_name(record_id) for record_id in ids]
    # Different ids have different folders, and each folder is one plain segment that a path keeps as written.
    assert len(set(names)) == len(ids)
    for name in names:
        assert "/" not in name and name.isascii()
        assert normalize_path(f"goals/{name}/brief.md") == f"goals/{name}/brief.md"
    assert folder_name("launch") == "launch" and folder_name("Docs-1_v2.x") == "Docs-1_v2.x"
    assert folder_name("me@example.com") == "me@example.com"
    assert folder_name("Docs Team") == "Docs%20Team" and folder_name("team/growth") == "team%2fgrowth"
    assert (folder_name("."), folder_name("..")) == ("%2e", "%2e.")
    for empty in ("", None):
        with pytest.raises(ValueError):
            folder_name(empty)
    # A Task's folder is named the same way. A caller still names the Task by its id.
    from agno.company.files import _locate

    location = _locate("tasks/Task 1/report.md")
    assert (location.folder, location.stored_folder, location.tree_path) == (
        "tasks/Task 1",
        "tasks/Task%201",
        "tasks/Task 1/report.md",
    )


@pytest.mark.parametrize("use_async", [False, True])
def test_goals_whose_ids_differ_by_a_slash_or_by_case_keep_their_pages_apart(system, use_async):
    manager = CompanyManager(system.db, system.os.registry)
    ids = ["team", "team/growth", "Docs", "docs", "café", "café"]
    for goal_id in ids:
        manager.create(name=goal_id, id=goal_id)
        manager.write_wiki(goal_id=goal_id, path="notes.md", content=f"Of {goal_id}", expected_version=0)
    manager.write_wiki(goal_id="team", path="growth/notes.md", content="The team's page", expected_version=0)

    for goal_id in ids:
        assert manager.read_wiki(goal_id, "notes.md").content == f"Of {goal_id}"
    assert sorted(page.path for page in manager.list_wiki("team", limit=100)[0]) == [
        "brief.md", "growth/notes.md", "notes.md", "status.md",
    ]  # fmt: skip
    assert sorted(page.path for page in manager.list_wiki("team/growth", limit=100)[0]) == [
        "brief.md", "notes.md", "status.md",
    ]  # fmt: skip
    # Each Goal has one folder of the store, named by its id written as one segment.
    folders = {
        path.split("/")[1] for path in stored(system.db) if path.startswith("goals/") and path.endswith("/notes.md")
    }
    assert folders >= {"team", "team%2fgrowth", "Docs", "docs", "cafe%cc%81", "caf%c3%a9"}
    # The tree reads a Goal by its id.
    files = tree(system.os)
    assert call(files, "read_company_file", None, use_async, path="goals/Docs/notes.md")["content"] == "Of Docs"
    assert call(files, "read_company_file", None, use_async, path="goals/docs/notes.md")["content"] == "Of docs"


# ------------------------------------------------------------------ where notes are written


@pytest.mark.parametrize("use_async", [False, True])
def test_notes_are_written_to_the_company_database_whatever_notes_database_is_named(tmp_path, use_async):
    company_db, os_db = SqliteDb(db_file=str(tmp_path / "company.db")), SqliteDb(db_file=str(tmp_path / "os.db"))
    tools = CompanyFileTools(company_db, notes_db=os_db)
    written = call(tools, "write_company_file", None, use_async, path="notes/ideas.md", content="A note")
    assert written["path"] == "notes/ideas.md"
    assert call(tools, "read_company_file", None, use_async, path="notes/ideas.md")["content"] == "A note"
    files = CompanyFiles(company_db, notes_db=os_db)
    assert files.read("notes/ideas.md")["content"] == "A note"

    assert stored(company_db) == {"notes/ideas.md": "A note"}
    assert stored(os_db) == {}
    # Leaving the notes database out still means a tree with no notes/.
    assert "notes" not in CompanyFiles(company_db).areas and "notes" in files.areas
    # Without a Company database the notes are in the database that is named.
    alone = CompanyFiles(notes_db=os_db)
    alone.write("notes/own.md", "Super Agent's")
    assert stored(os_db) == {"notes/own.md": "Super Agent's"}
    company_db.close()
    os_db.close()


# ------------------------------------------------------------------ a store at its limit


@pytest.mark.parametrize("use_async", [False, True])
def test_a_full_store_is_still_read(tmp_path, use_async):
    from fastapi.testclient import TestClient

    from agno.company.manager import AsyncCompanyManager

    db_file = str(tmp_path / "company.db")
    writer = SqliteDb(db_file=db_file)
    CompanyManager(writer).create(name="Launch", id="launch")
    for meta in company_filesystem(writer).list():
        company_filesystem(writer).delete(meta.path)
    company_filesystem(writer).write("wiki/people.md", "Ada")
    db = AsyncSqliteDb(db_file=db_file) if use_async else SqliteDb(db_file=db_file)
    # The store holds exactly what it may: no default page can be added to it.
    used = company_filesystem(writer).usage().total_bytes
    agent_os = AgentOS(db=db, company=CompanyConfig(max_filesystem_bytes=used), telemetry=False)

    with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
        listed = client.get("/company/wiki")
        assert listed.status_code == 200, listed.text
        assert [page["path"] for page in listed.json()["data"]] == ["people.md"]
        assert client.get("/company/wiki/people.md").json()["content"] == "Ada"
        assert client.get("/company/goals/launch/wiki").status_code == 200
        # A page that could not be created is not found. The limit is not the answer to a read.
        assert client.get("/company/wiki/brief.md").status_code == 404
        # A write that grows the store is refused with the limit, as before.
        grown = client.put("/company/wiki/new.md", json={"content": "More", "expected_version": 0})
        assert grown.status_code == 422 and "storage is full" in grown.text

    manager = AsyncCompanyManager(db) if use_async else CompanyManager(db)

    async def read() -> tuple:
        try:
            pages = manager.list_wiki(None)
            page = manager.read_wiki(None, "people.md")
            if use_async:
                pages, page = await pages, await page
            return [meta.path for meta in pages[0]], page.content
        finally:
            if use_async:
                await db.db_engine.dispose()

    assert asyncio.run(read()) == (["people.md"], "Ada")
    writer.close()


# ------------------------------------------------------------------ the limit, for every handle on a database


@pytest.mark.parametrize("use_async", [False, True])
def test_the_limit_holds_for_every_handle_on_the_database(tmp_path, monkeypatch, use_async):
    db_file = str(tmp_path / "data" / "company.db")
    (tmp_path / "data").mkdir()
    built_with = SqliteDb(db_file=db_file)
    AgentOS(db=built_with, company=CompanyConfig(max_filesystem_bytes=50), telemetry=False)
    cls = AsyncSqliteDb if use_async else SqliteDb
    scheme = "sqlite+aiosqlite" if use_async else "sqlite"
    monkeypatch.chdir(tmp_path)
    handles = [
        cls(db_file=db_file),
        cls(db_url=f"{scheme}:///{tmp_path}/data/../data/company.db"),
        cls(db_url=f"{scheme}:///data/company.db"),
    ]
    elsewhere = cls(db_file=str(tmp_path / "other.db"))

    # A handle AgentOS was not built with has the limit AgentOS was given.
    assert [company_filesystem(handle).max_namespace_bytes for handle in handles] == [50, 50, 50]
    assert company_folder(handles[0], "notes").max_namespace_bytes == 50
    # Another database has the default.
    assert company_filesystem(elsewhere).max_namespace_bytes == COMPANY_FILESYSTEM_BYTES

    async def fill() -> None:
        store = company_filesystem(handles[0])
        try:
            if use_async:
                await store.awrite("notes/a.md", "x" * 40)
                await store.awrite("notes/b.md", "x" * 40)
            else:
                store.write("notes/a.md", "x" * 40)
                store.write("notes/b.md", "x" * 40)
        finally:
            if use_async:
                await handles[0].db_engine.dispose()

    with pytest.raises(QuotaExceededError):
        asyncio.run(fill())
    assert stored(built_with) == {"notes/a.md": "x" * 40}
    built_with.close()


# ------------------------------------------------------------------ the users of a folder


@pytest.mark.parametrize("use_async", [False, True])
def test_a_folder_view_names_the_users_who_hold_files(tmp_path, use_async):
    from agno.company.filesystem import _Folder

    db_file = str(tmp_path / "files.db")
    writer = SqliteDb(db_file=db_file)
    whole = FileSystem(writer, namespace="team", user_scoped=True)
    whole.resolve(user_id="alice").write("docs/a.md", "Alice's")
    whole.resolve(user_id="bob").write("docs/b.md", "Bob's")
    db = AsyncSqliteDb(db_file=db_file) if use_async else writer
    backend = FileSystem(db, namespace="team", user_scoped=True).backend
    folder = FileSystem(backend=_Folder(backend, "docs"), namespace="team", user_scoped=True)

    async def users() -> list:
        try:
            return await folder.apartitions() if use_async else folder.partitions()
        finally:
            if use_async:
                await db.db_engine.dispose()

    assert asyncio.run(users()) == ["alice", "bob"]
    writer.close()


# ------------------------------------------------------------------ the length of a stored path


@pytest.mark.parametrize("use_async", [False, True])
def test_a_write_is_held_to_the_limits_of_the_path_as_it_is_stored(system, use_async):
    from agno.fs._paths import MAX_PATH_CHARS, MAX_SEGMENT_CHARS, MAX_SEGMENTS

    manager = CompanyManager(system.db, system.os.registry)
    manager.create(name="Launch", id="launch")
    files = tree(system.os)

    def deep(names: int, leaf: str = "page.md") -> str:
        return "/".join(["d"] * (names - 1) + [leaf])

    def write(path: str) -> dict:
        return call(files, "write_company_file", None, use_async, path=path, content="x", expected_version=0)

    # The tree takes a whole tree path, which is the path as it is stored: it holds at most MAX_SEGMENTS names.
    for folder, own in (("notes", 1), ("goals/launch", 2)):
        fits, over = deep(MAX_SEGMENTS - own), deep(MAX_SEGMENTS - own + 1)
        assert write(f"{folder}/{fits}")["path"] == f"{folder}/{fits}"
        with pytest.raises(InvalidPathError):
            write(f"{folder}/{over}")
    # The wiki takes a path inside its folder. It is held to what the folder's own name leaves of the limit.
    for goal_id, own in ((None, 1), ("launch", 2)):
        fits, over = deep(MAX_SEGMENTS - own, "wiki.md"), deep(MAX_SEGMENTS - own + 1, "wiki.md")
        with pytest.raises(InvalidPathError, match=f"at most {MAX_SEGMENTS - own} names deep"):
            manager.write_wiki(goal_id=goal_id, path=over, content="x", expected_version=0)
        assert manager.write_wiki(goal_id=goal_id, path=fits, content="x", expected_version=0).version == 1
    # The same for the length of the whole path.
    longest = MAX_PATH_CHARS - len("wiki/")
    name = "n" * (MAX_SEGMENT_CHARS - 3) + ".md"
    parts = [name] * (longest // (len(name) + 1))
    fits = "/".join([*parts, "x" * (longest - sum(len(part) + 1 for part in parts) - 3) + ".md"])
    assert len(f"wiki/{fits}") == MAX_PATH_CHARS
    assert manager.write_wiki(goal_id=None, path=fits, content="x", expected_version=0).version == 1
    with pytest.raises(InvalidPathError, match=f"{longest} characters"):
        manager.write_wiki(goal_id=None, path=fits[:-3] + "x.md", content="x", expected_version=0)
    # Appending to a file and moving one are writes too.
    notes = company_folder(system.db, "notes")
    notes.write("short.md", "x")
    for refused in (
        lambda: notes.append(deep(MAX_SEGMENTS, "log.md"), "x"),
        lambda: notes.move("short.md", deep(MAX_SEGMENTS, "moved.md")),
    ):
        with pytest.raises(InvalidPathError, match=f"at most {MAX_SEGMENTS - 1} names deep"):
            refused()
    # No stored path is past a limit.
    for path in stored(system.db):
        assert len(path) <= MAX_PATH_CHARS and path.count("/") < MAX_SEGMENTS, path

    # A file stored with a longer path, as the migration can leave one, is still read and listed.
    over = f"wiki/{deep(MAX_SEGMENTS)}"
    FileSystem(system.db, namespace="company", user_scoped=False).backend.write("company", over, "Kept from 3.2.0")
    assert manager.read_wiki(None, deep(MAX_SEGMENTS)).content == "Kept from 3.2.0"
    assert company_folder(system.db, "wiki").read(deep(MAX_SEGMENTS)) == "Kept from 3.2.0"
    assert deep(MAX_SEGMENTS) in [page.path for page in manager.list_wiki(None, limit=100)[0]]


def test_a_write_on_an_asynchronous_database_is_held_to_the_same_limits(tmp_path):
    from agno.company.manager import AsyncCompanyManager
    from agno.fs._paths import MAX_SEGMENTS

    db = AsyncSqliteDb(db_file=str(tmp_path / "company.db"))
    manager = AsyncCompanyManager(db)
    fits = "/".join(["d"] * (MAX_SEGMENTS - 2) + ["page.md"])

    async def write() -> int:
        try:
            with pytest.raises(InvalidPathError, match=f"at most {MAX_SEGMENTS - 1} names deep"):
                await manager.write_wiki(goal_id=None, path=f"d/{fits}", content="x", expected_version=0)
            with pytest.raises(InvalidPathError, match=f"at most {MAX_SEGMENTS - 1} names deep"):
                await company_folder(db, "notes").aappend(f"d/{fits}", "x")
            return (await manager.write_wiki(goal_id=None, path=fits, content="x", expected_version=0)).version
        finally:
            await db.db_engine.dispose()

    assert asyncio.run(write()) == 1


def test_a_migrate_route_does_not_move_notes_while_the_company_database_is_not_migrated(tmp_path):
    from fastapi.testclient import TestClient

    os_file, os_reader, company_db = _notes_left_in_the_agentos_database(tmp_path, "company/notes")
    # The Company database holds a page where 3.2.0 kept it.
    company_db._get_table("goals", create_table_if_not_found=True)
    FileSystem(company_db, namespace="company/wiki", user_scoped=False).write("handbook.md", "The handbook")
    agent_os = AgentOS(db=os_reader, company=CompanyConfig(db=company_db), telemetry=False)

    def notes_in_the_agentos_database() -> list:
        spaces = [FileSystem(os_reader, namespace=name, user_scoped=False) for name in ("company", "company/notes")]
        return [meta.path for files in spaces for meta in files.list()]

    with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
        # Only the AgentOS database is migrated. The Company database still holds files where 3.2.0 kept them.
        assert client.post(f"/databases/{os_reader.id}/migrate").status_code == 200
        assert _refused(client.get("/company/notes/ideas.md"))
        # The note is where it was: it is not moved into a store that is still to be migrated.
        assert len(notes_in_the_agentos_database()) == 1

        # With both migrated, the route moves the notes.
        assert client.post("/databases/all/migrate").status_code == 200
        assert client.get("/company/notes/ideas.md").json()["content"] == "A note"
    assert notes_in_the_agentos_database() == []
    assert stored(company_db)["wiki/handbook.md"] == "The handbook"
    os_reader.close()
    company_db.close()


def test_a_goal_whose_id_is_longer_than_a_name_keeps_its_pages(system):
    from agno.fs._paths import MAX_PATH_CHARS, MAX_SEGMENT_CHARS

    manager = CompanyManager(system.db, system.os.registry)
    # An id whose folder name is longer than a name of a path may be: 3.2.0 kept its pages, and so does this.
    long_id = "\u540d" * 50
    assert len(company_folder(system.db, f"goals/{folder_name(long_id)}").backend.folder) > MAX_SEGMENT_CHARS
    manager.create(name="Long", id=long_id)
    written = manager.write_wiki(goal_id=long_id, path="notes/plan.md", content="The plan", expected_version=0)
    assert written.version == 1 and manager.read_wiki(long_id, "notes/plan.md").content == "The plan"
    assert sorted(page.path for page in manager.list_wiki(long_id, limit=100)[0]) == [
        "brief.md",
        "notes/plan.md",
        "status.md",
    ]

    # An id so long that its folder leaves no room in a path: what the migration stored is read, nothing is written.
    longest = "g" * MAX_PATH_CHARS
    manager.create(name="Longest", id=longest)
    FileSystem(system.db, namespace="company", user_scoped=False).backend.write(
        "company", f"goals/{longest}/status.md", "Kept from 3.2.0"
    )
    assert [page.path for page in manager.list_wiki(longest, limit=100)[0]] == ["status.md"]
    assert manager.read_wiki(longest, "status.md").content == "Kept from 3.2.0"
    with pytest.raises(InvalidPathError, match="and 0 characters"):
        manager.write_wiki(goal_id=longest, path="new.md", content="x", expected_version=0)


@pytest.mark.parametrize("use_async", [False, True])
def test_a_folder_with_a_limit_of_its_own_holds_every_write_and_append_to_it(tmp_path, use_async):
    db = (AsyncSqliteDb if use_async else SqliteDb)(db_file=str(tmp_path / "files.db"))
    capped = company_folder(db, "tasks/t", max_folder_bytes=1500)
    other = company_folder(db, "tasks/u", max_folder_bytes=1500)

    async def run() -> None:
        async def do(store, method: str, *args, **kwargs):
            if use_async:
                return await getattr(store, f"a{method}")(*args, **kwargs)
            return getattr(store, method)(*args, **kwargs)

        await do(capped, "write", "report.md", "x" * 1000)
        with pytest.raises(QuotaExceededError, match="folder is full") as refused:
            await do(capped, "append", "log.md", "y" * 600)
        assert (refused.value.scope, refused.value.current, refused.value.limit) == ("folder", 1000, 1500)
        with pytest.raises(QuotaExceededError, match="folder is full"):
            await do(capped, "write", "more.md", "y" * 600)
        # A file of the same size in its place does not grow the folder.
        assert (await do(capped, "write", "report.md", "z" * 1000)).version == 2
        assert (await do(other, "append", "log.md", "y" * 600)).path == "log.md"
        if use_async:
            await db.db_engine.dispose()

    asyncio.run(run())
