"""The Company file system on the File System page, and the route that lists every file system."""

import logging

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.company.filesystem import company_filesystem
from agno.company.manager import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry import Registry
from tests.unit.os.test_company_file_tree import call, records, tree
from tests.unit.os.test_mini_agent_tasks import ScriptedModel, System, headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

FILES_ONLY = ["filesystem:read"]
COMPANY_ENTRY = {
    "backend_type": "db",
    "table_name": "agno_fs",
    "namespace": "company",
    "user_isolation": False,
    "max_file_bytes": 1_000_000,
    "max_namespace_bytes": 1_000_000_000,
    "id": "company",
    "declared": False,
    "company": True,
    "agents": [],
}


@pytest.fixture
def system(tmp_path):
    value = System(tmp_path)
    yield value
    value.db.close()


def written(system) -> dict:
    """Company records, and one file in each folder of the tree, written as agents and people write them."""
    ids = records(system)
    files = tree(system.os)
    call(files, "write_company_file", path=f"tasks/{ids['task']}/report.md", content="The report needle")
    page = f"goals/{ids['goal']}/research.md"
    call(files, "write_company_file", path=page, content="Research needle", expected_version=0)
    call(files, "write_company_file", path="notes/ideas.md", content="A note needle")
    CompanyManager(system.db).write_wiki(goal_id=None, path="people.md", content="Ada needle\n", expected_version=0)
    return ids


def entry_of(entries: list, namespace: str) -> dict:
    found = [entry for entry in entries if entry["namespace"] == namespace]
    assert len(found) == 1, entries
    return {key: value for key, value in found[0].items() if key != "db_id"}


# ------------------------------------------------------------------ the Company file system


def test_the_company_filesystem_is_listed_and_read_with_filesystem_read_alone(system):
    ids = written(system)
    caller = headers(FILES_ONLY)

    config = system.client.get("/config", headers=headers(["config:read"]))
    assert config.status_code == 200
    assert entry_of(config.json()["filesystem"]["namespaces"], "company") == COMPANY_ENTRY
    listed = system.client.get("/filesystem/namespaces", headers=caller)
    assert listed.status_code == 200
    assert entry_of(listed.json()["namespaces"], "company") == COMPANY_ENTRY

    # The tree is under the namespace: one entry, with the four folders in it.
    by_id = {"filesystem_id": "company"}
    top = system.client.get("/filesystem/entries", params=by_id, headers=caller)
    assert top.status_code == 200
    assert (top.json()["filesystem_id"], top.json()["namespace"], top.json()["agent_ids"]) == ("company", "company", [])
    assert [(entry["path"], entry["type"]) for entry in top.json()["entries"]] == [
        ("goals", "directory"),
        ("notes", "directory"),
        ("tasks", "directory"),
        ("wiki", "directory"),
    ]
    goals = system.client.get("/filesystem/entries", params={**by_id, "directory": "goals"}, headers=caller)
    # A Goal is a folder once it holds a page.
    assert [(entry["path"], entry["type"]) for entry in goals.json()["entries"]] == [
        (f"goals/{ids['goal']}", "directory")
    ]
    goal = system.client.get(
        "/filesystem/entries", params={**by_id, "directory": f"goals/{ids['goal']}"}, headers=caller
    )
    assert [entry["path"].rsplit("/", 1)[1] for entry in goal.json()["entries"]] == [
        "brief.md",
        "research.md",
        "status.md",
    ]

    # A file an agent wrote is read here by a caller with neither wiki:read nor tasks:read.
    for path, content in (
        (f"tasks/{ids['task']}/report.md", "The report needle"),
        (f"goals/{ids['goal']}/research.md", "Research needle"),
        ("notes/ideas.md", "A note needle"),
        ("wiki/people.md", "Ada needle\n"),
    ):
        read = system.client.get("/filesystem/content", params={**by_id, "path": path}, headers=caller)
        assert read.status_code == 200, path
        assert read.json()["content"] == content
    search = system.client.get("/filesystem/search", params={**by_id, "query": "needle"}, headers=caller)
    assert sorted(entry["path"] for entry in search.json()["entries"]) == sorted(
        [f"tasks/{ids['task']}/report.md", f"goals/{ids['goal']}/research.md", "notes/ideas.md", "wiki/people.md"]
    )
    rows = system.client.get("/filesystem/files", params={**by_id, "limit": 100}, headers=caller).json()["entries"]
    assert {row["filesystem_id"] for row in rows} == {"company"}
    assert f"tasks/{ids['task']}/report.md" in [row["path"] for row in rows]

    # The Company routes still ask for their own scopes.
    for url in ("/company/wiki", "/company/notes", f"/company/tasks/{ids['task']}/files"):
        assert system.client.get(url, headers=caller).status_code == 403, url


def test_a_request_by_namespace_alone_reads_the_company_filesystem(system):
    ids = written(system)
    caller = headers(FILES_ONLY)
    by_namespace = {"namespace": "company"}

    top = system.client.get("/filesystem/entries", params=by_namespace, headers=caller)
    assert top.status_code == 200
    assert [entry["path"] for entry in top.json()["entries"]] == ["goals", "notes", "tasks", "wiki"]
    read = system.client.get(
        "/filesystem/content", params={**by_namespace, "path": f"tasks/{ids['task']}/report.md"}, headers=caller
    )
    assert read.status_code == 200 and read.json()["content"] == "The report needle"
    assert read.json()["filesystem_id"] == "company"
    # The namespace filters the list and the table of files.
    only = system.client.get("/filesystem/namespaces", params=by_namespace, headers=caller)
    assert [entry["namespace"] for entry in only.json()["namespaces"]] == ["company"]
    rows = system.client.get("/filesystem/files", params={**by_namespace, "limit": 100}, headers=caller).json()
    assert rows["entries"] and {row["namespace"] for row in rows["entries"]} == {"company"}
    assert system.client.get("/filesystem/namespaces", params={"namespace": "missing"}, headers=caller).json() == {
        "namespaces": []
    }


def test_reading_the_company_filesystem_needs_filesystem_read(system):
    ids = written(system)

    for scopes in (["wiki:read", "tasks:read"], ["config:read"], ["agents:read"], []):
        refused = headers(scopes)
        assert system.client.get("/filesystem/namespaces", headers=refused).status_code == 403, scopes
        content = system.client.get(
            "/filesystem/content",
            params={"filesystem_id": "company", "path": f"tasks/{ids['task']}/report.md"},
            headers=refused,
        )
        assert content.status_code == 403, scopes
        assert "needle" not in content.text


def test_a_request_for_the_company_filesystem_loads_no_agent(system, monkeypatch):
    from agno.os.routers.filesystem import router as filesystem_router

    ids = written(system)
    resolved: list = []
    resolve_agent = filesystem_router.resolve_agent

    async def spy(agent_id, *args, **kwargs):
        resolved.append(agent_id)
        return await resolve_agent(agent_id, *args, **kwargs)

    monkeypatch.setattr(filesystem_router, "resolve_agent", spy)

    for path, params in (
        ("/filesystem/entries", {}),
        ("/filesystem/content", {"path": f"tasks/{ids['task']}/report.md"}),
        ("/filesystem/search", {"query": "needle"}),
        ("/filesystem/files", {}),
    ):
        response = system.client.get(path, params={"filesystem_id": "company", **params}, headers=headers(FILES_ONLY))
        assert response.status_code == 200, path
    assert resolved == []


def test_the_company_filesystem_is_shared_under_user_isolation(tmp_path):
    system = System(tmp_path, user_isolation=True)
    try:
        written(system)
        for user in ("alice", "bob"):
            caller = headers(FILES_ONLY, user=user)
            entry = entry_of(
                system.client.get("/filesystem/namespaces", headers=caller).json()["namespaces"], "company"
            )
            assert entry["user_isolation"] is False
            read = system.client.get(
                "/filesystem/content", params={"filesystem_id": "company", "path": "notes/ideas.md"}, headers=caller
            )
            assert (read.json()["content"], read.json()["user_id"]) == ("A note needle", None)
    finally:
        system.db.close()


def test_without_company_the_notes_store_is_not_listed(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    agent_os = AgentOS(db=db, manager=OSManager(model=ScriptedModel()), telemetry=False)
    try:
        call(tree(agent_os), "write_company_file", path="notes/ideas.md", content="A note")
        assert company_filesystem(db).read("notes/ideas.md") == "A note"
        with TestClient(agent_os.get_app()) as client:
            assert client.get("/config").json()["filesystem"]["namespaces"] == []
            assert client.get("/filesystem/namespaces").json() == {"namespaces": []}
            by_id = client.get("/filesystem/content", params={"filesystem_id": "company", "path": "notes/ideas.md"})
            assert by_id.status_code == 404
            assert "A note" not in by_id.text
    finally:
        db.close()


def test_a_database_that_cannot_hold_files_has_no_company_entry():
    from agno.db.in_memory import InMemoryDb

    with TestClient(AgentOS(db=InMemoryDb(), company=CompanyConfig(), telemetry=False).get_app()) as client:
        assert client.get("/config").json()["filesystem"]["namespaces"] == []
        assert client.get("/filesystem/namespaces").json() == {"namespaces": []}


def test_the_company_store_declared_or_held_by_an_agent_is_one_entry(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    declared = FileSystem(db, namespace="company", user_scoped=False)
    reader = Agent(
        id="reader", db=db, filesystem=FileSystem(db, namespace="company", user_scoped=False, read_only=True)
    )
    agent_os = AgentOS(db=db, agents=[reader], company=CompanyConfig(), filesystem=declared, telemetry=False)
    try:
        company_filesystem(db).write("wiki/people.md", "Ada")
        with TestClient(agent_os.get_app()) as client:
            for entries in (
                client.get("/config").json()["filesystem"]["namespaces"],
                client.get("/filesystem/namespaces").json()["namespaces"],
            ):
                assert [(e["id"], e["declared"], e["company"], e["agents"]) for e in entries] == [
                    ("company", True, True, [{"id": "reader", "access": "read_only"}])
                ]
            read = client.get("/filesystem/content", params={"filesystem_id": "company", "path": "wiki/people.md"})
            assert read.json()["content"] == "Ada"
    finally:
        db.close()


# ------------------------------------------------------------------ the list of file systems


def test_the_list_sees_the_agents_the_browse_routes_see(tmp_path):
    catalog_db = SqliteDb(id="catalog-db", db_file=str(tmp_path / "catalog.db"))
    files_db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    stored_store = FileSystem(files_db, namespace="stored-notes")
    stored_store.write("state.md", "from a stored agent")
    Agent(id="stored-agent", db=catalog_db, filesystem=stored_store).save()
    factory_store = FileSystem(catalog_db, namespace="factories/{agent_id}")
    factory_store.resolve(agent_id="factory-agent").write("state.md", "from a factory agent")
    factory = AgentFactory(
        id="factory-agent",
        db=catalog_db,
        factory=lambda ctx: Agent(id="factory-agent", db=catalog_db, filesystem=factory_store),
    )
    code_agent = Agent(
        id="code-agent", db=catalog_db, filesystem=FileSystem(catalog_db, namespace="code", read_only=True)
    )
    handbook = FileSystem(catalog_db, namespace="handbook")
    agent_os = AgentOS(
        db=catalog_db,
        agents=[code_agent, factory],
        registry=Registry(dbs=[files_db]),
        filesystem=handbook,
        telemetry=False,
    )
    try:
        with TestClient(agent_os.get_app()) as client:
            # /config describes the agents declared in code, and not a stored or a factory agent.
            config = client.get("/config").json()["filesystem"]["namespaces"]
            assert sorted(entry["id"] for entry in config) == ["code", "handbook"]

            listed = client.get("/filesystem/namespaces").json()["namespaces"]
            assert [(e["id"], e["namespace"], e["declared"], e["company"], e["agents"]) for e in listed] == [
                ("code", "code", False, False, [{"id": "code-agent", "access": "read_only"}]),
                ("factories/factory-agent", "factories/factory-agent", False, False, [{"id": "factory-agent"}]),
                ("handbook", "handbook", True, False, []),
                ("stored-notes", "stored-notes", False, False, [{"id": "stored-agent"}]),
            ]
            assert {entry["id"]: entry["db_id"] for entry in listed}["stored-notes"] == "files-db"
            # Every id the list gives is one the browse routes take.
            for entry, content in (
                ("stored-notes", "from a stored agent"),
                ("factories/factory-agent", "from a factory agent"),
            ):
                read = client.get("/filesystem/content", params={"filesystem_id": entry, "path": "state.md"})
                assert read.status_code == 200 and read.json()["content"] == content
            # The list narrows to one agent, as the other routes do.
            of_agent = client.get("/filesystem/namespaces", params={"agent_id": "stored-agent"}).json()["namespaces"]
            assert [entry["id"] for entry in of_agent] == ["stored-notes"]
            for params in ({}, {"agent_id": ""}):
                assert len(client.get("/filesystem/namespaces", params=params).json()["namespaces"]) == 4
            assert client.get("/filesystem/namespaces", params={"agent_id": "missing"}).status_code == 404
    finally:
        catalog_db.close()
        files_db.close()


def test_an_id_from_config_can_name_two_stores_that_the_list_tells_apart(tmp_path):
    main = SqliteDb(id="main-db", db_file=str(tmp_path / "main.db"))
    archive = SqliteDb(id="archive-db", db_file=str(tmp_path / "archive.db"))
    code_store, factory_store = FileSystem(main, namespace="notes"), FileSystem(archive, namespace="notes")
    code_store.write("state.md", "the code agent's")
    factory_store.write("state.md", "the factory agent's")
    factory = AgentFactory(
        id="factory-agent",
        db=main,
        factory=lambda ctx: Agent(id="factory-agent", db=main, filesystem=factory_store),
    )
    agent_os = AgentOS(
        db=main, agents=[Agent(id="code-agent", db=main, filesystem=code_store), factory], telemetry=False
    )
    try:
        with TestClient(agent_os.get_app()) as client:
            # /config describes the agent declared in code alone, so its store is named by the namespace.
            config = client.get("/config").json()["filesystem"]["namespaces"]
            assert [entry["id"] for entry in config] == ["notes"]
            # The routes also see the factory agent's store. There the namespace names two stores.
            by_config_id = client.get("/filesystem/entries", params={"filesystem_id": "notes"})
            assert by_config_id.status_code == 409
            assert "/filesystem/namespaces" in by_config_id.json()["detail"]

            # The list gives each store the id the routes take.
            listed = client.get("/filesystem/namespaces").json()["namespaces"]
            assert [(entry["id"], entry["agents"]) for entry in listed] == [
                ("notes:archive-db", [{"id": "factory-agent"}]),
                ("notes:main-db", [{"id": "code-agent"}]),
            ]
            for filesystem_id, content in (
                ("notes:main-db", "the code agent's"),
                ("notes:archive-db", "the factory agent's"),
            ):
                read = client.get("/filesystem/content", params={"filesystem_id": filesystem_id, "path": "state.md"})
                assert read.status_code == 200 and read.json()["content"] == content
            # A store has the same id when the list or a listing of files is narrowed to one agent.
            for agent_id, filesystem_id in (("code-agent", "notes:main-db"), ("factory-agent", "notes:archive-db")):
                of_agent = client.get("/filesystem/namespaces", params={"agent_id": agent_id}).json()["namespaces"]
                assert [(entry["id"], entry["agents"]) for entry in of_agent] == [(filesystem_id, [{"id": agent_id}])]
                rows = client.get("/filesystem/files", params={"agent_id": agent_id}).json()["entries"]
                assert [(row["filesystem_id"], row["path"]) for row in rows] == [(filesystem_id, "state.md")]
    finally:
        main.close()
        archive.close()


def test_the_company_id_with_an_agent_opens_it_only_when_that_agent_holds_it(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    holder = Agent(
        id="holder", db=db, filesystem=FileSystem(db, namespace="company", user_scoped=False, read_only=True)
    )
    other = Agent(id="other", db=db, filesystem=FileSystem(db, namespace="other-notes"))
    agent_os = AgentOS(db=db, agents=[holder, other], company=CompanyConfig(), telemetry=False)
    try:
        company_filesystem(db).write("wiki/people.md", "Ada")
        with TestClient(agent_os.get_app()) as client:

            def opened(**params) -> tuple:
                response = client.get("/filesystem/entries", params=params)
                return response.status_code, response.json().get("filesystem_id")

            assert opened(filesystem_id="company") == (200, "company")
            assert opened(filesystem_id="company", agent_id="holder") == (200, "company")
            # The other agent does not hold the Company filesystem, so the two name nothing.
            assert opened(filesystem_id="company", agent_id="other") == (404, None)
            assert opened(agent_id="other") == (200, "other-notes")

            def listed(agent_id: str) -> list:
                entries = client.get("/filesystem/namespaces", params={"agent_id": agent_id}).json()["namespaces"]
                return [(entry["id"], entry["company"], entry["agents"]) for entry in entries]

            assert listed("holder") == [("company", True, [{"id": "holder", "access": "read_only"}])]
            assert listed("other") == [("other-notes", False, [{"id": "other"}])]
    finally:
        db.close()


def test_every_id_the_list_gives_opens_on_every_route(tmp_path):
    db = SqliteDb(id="main-db", db_file=str(tmp_path / "main.db"))
    archive = SqliteDb(id="archive-db", db_file=str(tmp_path / "archive.db"))
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "plain needle")
    held = FileSystem(db, namespace="held")
    held.write("draft.md", "held needle")
    # Two stores under one namespace, one of them only a factory agent holds: each needs a longer id.
    notes_here, notes_there = FileSystem(db, namespace="notes"), FileSystem(archive, namespace="notes")
    notes_here.write("a.md", "here needle")
    notes_there.write("b.md", "there needle")
    factory = AgentFactory(
        id="factory-agent", db=db, factory=lambda ctx: Agent(id="factory-agent", db=db, filesystem=notes_there)
    )
    agents = [Agent(id="keeper", db=db, filesystem=held), Agent(id="noter", db=db, filesystem=notes_here), factory]
    agent_os = AgentOS(db=db, agents=agents, company=CompanyConfig(), filesystem=handbook, telemetry=False)
    # Goals whose ids are not plain names: each folder of the Company file system is the id as one segment.
    manager = CompanyManager(db)
    for goal_id in ("Docs Team", "team/growth", "launch"):
        manager.create(name=goal_id, id=goal_id)
        manager.write_wiki(goal_id=goal_id, path="status.md", content=f"{goal_id} needle", expected_version=1)
    company_filesystem(db).write("notes/ideas.md", "a note needle")
    try:
        with TestClient(agent_os.get_app()) as client:
            listed = client.get("/filesystem/namespaces").json()["namespaces"]
            ids = [entry["id"] for entry in listed]
            assert sorted(ids) == ["company", "handbook", "held", "notes:archive-db", "notes:main-db"]
            assert [entry["id"] for entry in listed if entry["company"]] == ["company"]

            for filesystem_id in ids:
                by_id = {"filesystem_id": filesystem_id}
                rows = client.get("/filesystem/files", params=by_id)
                assert rows.status_code == 200, filesystem_id
                paths = [row["path"] for row in rows.json()["entries"]]
                assert paths and {row["filesystem_id"] for row in rows.json()["entries"]} == {filesystem_id}
                opened = client.get("/filesystem/entries", params=by_id)
                assert (opened.status_code, opened.json()["filesystem_id"]) == (200, filesystem_id)
                found = client.get("/filesystem/search", params={**by_id, "query": "needle"})
                assert found.status_code == 200 and found.json()["filesystem_id"] == filesystem_id
                matched = {entry["path"] for entry in found.json()["entries"]}
                assert matched and matched <= set(paths)
                # Every path a listing gives is read back under the same id.
                for path in paths:
                    read = client.get("/filesystem/content", params={**by_id, "path": path})
                    assert read.status_code == 200, (filesystem_id, path)
                    assert read.json()["filesystem_id"] == filesystem_id
                    assert ("needle" in read.json()["content"]) is (path in matched)

            # In the Company entry a Goal's folder is its id as one segment, and the pages under it open.
            goals = client.get("/filesystem/entries", params={"filesystem_id": "company", "directory": "goals"})
            assert sorted(entry["path"] for entry in goals.json()["entries"]) == [
                "goals/Docs%20Team",
                "goals/launch",
                "goals/team%2fgrowth",
            ]
            for folder, goal_id in (("goals/Docs%20Team", "Docs Team"), ("goals/team%2fgrowth", "team/growth")):
                pages = client.get("/filesystem/entries", params={"filesystem_id": "company", "directory": folder})
                assert sorted(entry["path"] for entry in pages.json()["entries"]) == [
                    f"{folder}/brief.md",
                    f"{folder}/status.md",
                ]
                page = client.get(
                    "/filesystem/content", params={"filesystem_id": "company", "path": f"{folder}/status.md"}
                )
                assert page.status_code == 200 and page.json()["content"] == f"{goal_id} needle"
    finally:
        db.close()
        archive.close()


def test_the_list_describes_each_filesystem_as_config_does(tmp_path):
    db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    shared = FileSystem(db, namespace="shared")
    analyst = Agent(id="analyst", db=db, filesystem=[FileSystem(db, namespace="shared", read_only=True), shared])
    reader = Agent(id="reader", db=db, filesystem=FileSystem(db, namespace="shared", read_only=True))
    # Declared, and partitioned by user: a caller with no identity cannot read it, and it is still listed.
    scoped = FileSystem(db, namespace="diary", user_scoped=True)
    journals = FileSystem(db, namespace="journals/{user_id}")
    agent_os = AgentOS(db=db, agents=[analyst, reader], filesystem=[scoped, journals], telemetry=False)
    try:
        with TestClient(agent_os.get_app()) as client:
            listed = client.get("/filesystem/namespaces").json()["namespaces"]
            assert listed == client.get("/config").json()["filesystem"]["namespaces"]
            assert [(e["id"], e["declared"], e["user_isolation"], e["agents"]) for e in listed] == [
                ("diary", True, True, []),
                ("journals/{user_id}", True, True, []),
                # A writable attachment takes precedence over a read-only one of the same agent.
                ("shared", False, False, [{"id": "analyst"}, {"id": "reader", "access": "read_only"}]),
            ]
    finally:
        db.close()


def test_the_list_shows_only_what_the_caller_can_reach(system_with_stores):
    system, _ = system_with_stores

    def ids(scopes) -> list:
        response = system.client.get("/filesystem/namespaces", headers=headers(scopes))
        assert response.status_code == 200, (scopes, response.text)
        return sorted((entry["id"], entry["agents"]) for entry in response.json()["namespaces"])

    # filesystem:read alone: what the AgentOS holds itself.
    assert ids(FILES_ONLY) == [("company", []), ("handbook", [])]
    # With access to the agent that holds one, that filesystem too, and the agent is named.
    assert ids([*FILES_ONLY, "agents:writer:read"]) == [
        ("company", []),
        ("handbook", []),
        ("writer-notes", [{"id": "writer"}]),
    ]


def test_an_agent_that_cannot_be_loaded_is_left_out_of_the_list(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "files.db"))

    def build(ctx):
        raise RuntimeError("this agent cannot be built")

    broken = AgentFactory(id="broken", db=db, factory=build)
    notes = Agent(id="notes", db=db, filesystem=True)
    agent_os = AgentOS(db=db, agents=[broken, notes], filesystem=FileSystem(db, namespace="handbook"), telemetry=False)
    try:
        with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
            listed = client.get("/filesystem/namespaces")
            assert listed.status_code == 200
            assert [entry["id"] for entry in listed.json()["namespaces"]] == ["handbook", "notes"]
            # The table of files reads every agent and fails with the one that cannot be built.
            assert client.get("/filesystem/files").status_code == 500
            # Naming the agent that cannot be built still says so.
            assert client.get("/filesystem/namespaces", params={"agent_id": "broken"}).status_code == 500
    finally:
        db.close()


def test_the_list_gives_two_stores_with_one_namespace_two_ids(tmp_path):
    main, archive = (
        SqliteDb(id="main-db", db_file=str(tmp_path / "main.db")),
        SqliteDb(id="archive-db", db_file=str(tmp_path / "archive.db")),
    )
    stores = [FileSystem(main, namespace="handbook"), FileSystem(archive, namespace="handbook")]
    stores[0].write("style.md", "main")
    stores[1].write("style.md", "archive")
    try:
        with TestClient(AgentOS(db=main, filesystem=stores, telemetry=False).get_app()) as client:
            listed = client.get("/filesystem/namespaces", params={"namespace": "handbook"}).json()["namespaces"]
            assert [(e["id"], e["namespace"], e["db_id"]) for e in listed] == [
                ("handbook:archive-db", "handbook", "archive-db"),
                ("handbook:main-db", "handbook", "main-db"),
            ]
            for entry, content in (("handbook:main-db", "main"), ("handbook:archive-db", "archive")):
                read = client.get("/filesystem/content", params={"filesystem_id": entry, "path": "style.md"})
                assert read.json()["content"] == content
    finally:
        main.close()
        archive.close()


@pytest.fixture
def system_with_stores(tmp_path):
    """Company on, one declared filesystem, and one filesystem only the writer agent holds."""
    db = SqliteDb(db_file=str(tmp_path / "stores.db"))
    handbook = FileSystem(db, namespace="handbook", user_scoped=False)
    value = System(tmp_path, filesystem=handbook)
    value.writer.filesystem = FileSystem(value.db, namespace="writer-notes")
    # The writer was initialized before it was given a filesystem.
    value.os.resync(value.client.app)
    yield value, db
    value.db.close()
    db.close()


# ------------------------------------------------------------------ a stored path longer than a write accepts


DEEP_PAGE = "/".join(f"d{index}" for index in range(15)) + "/page.md"  # 16 names: as deep as the wiki API allows


def test_a_wiki_page_as_deep_as_3_2_0_allows_is_listed_and_read_after_the_migration(tmp_path, caplog):
    from agno.db.migrations.versions.v3_3_0 import move_company_files
    from agno.fs._paths import MAX_SEGMENTS, exceeds_write_limits

    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    # As 3.2.0 stores it: a page of the company wiki, in the wiki's own namespace.
    assert len(DEEP_PAGE.split("/")) == MAX_SEGMENTS
    wiki = FileSystem(db, namespace="company/wiki", user_scoped=False)
    wiki.write(DEEP_PAGE, "Deep page needle")
    wiki.write("brief.md", "# Company\n")

    with caplog.at_level(logging.WARNING):
        assert move_company_files(db) is True
    stored = f"wiki/{DEEP_PAGE}"
    assert exceeds_write_limits(stored) and not exceeds_write_limits("wiki/brief.md")
    # The migration names each path that is now longer than a write accepts, and only those.
    reports = [record.getMessage() for record in caplog.records if "longer than a write accepts" in record.getMessage()]
    assert len(reports) == 1 and stored in reports[0] and "wiki/brief.md" not in reports[0]
    assert reports[0].startswith("1 Company files")

    try:
        with TestClient(AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()) as client:
            by_id = {"filesystem_id": "company"}
            # Listed at every level, read, searched and shown in the table of files.
            folder = stored.rsplit("/", 1)[0]
            listed = client.get("/filesystem/entries", params={**by_id, "directory": folder})
            assert listed.status_code == 200, listed.text
            assert [(entry["path"], entry["type"]) for entry in listed.json()["entries"]] == [(stored, "file")]
            top = client.get("/filesystem/entries", params={**by_id, "directory": "wiki"})
            assert [entry["path"] for entry in top.json()["entries"]] == ["wiki/d0", "wiki/brief.md"]
            read = client.get("/filesystem/content", params={**by_id, "path": stored})
            assert read.status_code == 200, read.text
            assert (read.json()["content"], read.json()["path"]) == ("Deep page needle", stored)
            search = client.get("/filesystem/search", params={**by_id, "query": "needle", "directory": folder})
            assert [entry["path"] for entry in search.json()["entries"]] == [stored]
            rows = client.get("/filesystem/files", params=by_id).json()["entries"]
            assert stored in [row["path"] for row in rows]
            # The wiki API reads it too, by its path inside the wiki.
            assert client.get(f"/company/wiki/{DEEP_PAGE}").json()["content"] == "Deep page needle"
            # A path that is not a path is still refused, and a file that is not stored is not found.
            assert client.get("/filesystem/content", params={**by_id, "path": "wiki/../notes/x.md"}).status_code == 400
            assert client.get("/filesystem/content", params={**by_id, "path": stored + ".gone"}).status_code == 404
    finally:
        db.close()

    # The whole store still refuses to write a path that long.
    from agno.fs.errors import InvalidPathError

    with pytest.raises(InvalidPathError):
        company_filesystem(db).write(stored + "x", "new")


def test_the_migration_reports_nothing_when_every_path_fits(tmp_path, caplog):
    from agno.db.migrations.versions.v3_3_0 import move_company_files

    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    FileSystem(db, namespace="company/wiki", user_scoped=False).write("a/b/c.md", "Fits")
    FileSystem(db, namespace="company/notes", user_scoped=False).write("ideas.md", "Fits")
    try:
        with caplog.at_level(logging.WARNING):
            assert move_company_files(db) is True
        assert not [record for record in caplog.records if "longer than a write accepts" in record.getMessage()]
    finally:
        db.close()
