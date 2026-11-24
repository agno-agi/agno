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
)
from agno.company.manager import CompanyManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.fs import FileSystem
from agno.fs.errors import InvalidPathError, QuotaExceededError
from agno.os import AgentOS, CompanyConfig, OSManager
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
