from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent, RemoteAgent
from agno.agent.factory import AgentFactory
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.os import AgentOS, Authorization
from agno.registry import Registry

JWT_SECRET = "test-secret-for-filesystem-routes-32-bytes"
OS_ID = "filesystem-route-tests"


def _token(user_id: str, scopes: list[str] | None = None) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "aud": OS_ID,
            "scopes": scopes if scopes is not None else ["agents:read", "filesystem:read"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _headers(user_id: str, scopes: list[str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, scopes)}"}


@pytest.fixture
def db(tmp_path):
    database = SqliteDb(id="filesystem-db", db_file=str(tmp_path / "files.db"))
    try:
        yield database
    finally:
        database.db_engine.dispose()


@pytest.fixture
def client_factory():
    with ExitStack() as cleanup:

        def create(
            *agents, user_isolation: bool = False, db=None, registry=None, filesystem=None, authorization: bool = True
        ) -> TestClient:
            agent_os = AgentOS(
                id=OS_ID,
                agents=list(agents),
                db=db,
                registry=registry,
                filesystem=filesystem,
                authorization=Authorization(verification_keys=[JWT_SECRET], algorithm="HS256")
                if authorization
                else False,
                user_isolation=user_isolation,
            )
            client = TestClient(agent_os.get_app(), raise_server_exceptions=False)
            cleanup.callback(client.close)
            return client

        yield create


def test_list_read_and_search_run_behind_auth_middleware(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)
    assert agent.filesystem_instance is not None
    agent.filesystem_instance.write("notes/state.md", "alpha needle\nbeta\n")

    assert client.get("/filesystem/files").status_code == 401
    assert client.get("/filesystem/entries", params={"agent_id": "notes"}).status_code == 401

    listed = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_headers("alice"))
    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["notes"]

    content = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "notes/state.md"},
        headers=_headers("alice"),
    )
    assert content.status_code == 200
    assert content.json()["content"] == "alpha needle\nbeta\n"

    search = client.get(
        "/filesystem/search",
        params={"agent_id": "notes", "query": "needle"},
        headers=_headers("alice"),
    )
    assert search.status_code == 200
    assert [entry["path"] for entry in search.json()["entries"]] == ["notes/state.md"]


def test_global_files_lists_and_searches_configured_agent_filesystems(db, client_factory):
    notes = Agent(id="notes", db=db, filesystem=True)
    reports = Agent(id="reports", db=db, filesystem=True)
    client = client_factory(notes, reports)
    assert notes.filesystem_instance is not None
    notes.filesystem_instance.write("notes/state.md", "alpha needle")
    assert reports.filesystem_instance is not None
    reports.filesystem_instance.write("reports/summary.md", "beta")

    listed = client.get("/filesystem/files", headers=_headers("alice"))
    searched = client.get("/filesystem/files", params={"query": "needle"}, headers=_headers("alice"))
    filtered = client.get("/filesystem/files", params={"agent_id": "reports"}, headers=_headers("alice"))

    assert listed.status_code == 200
    assert [(entry["agent_ids"], entry["path"]) for entry in listed.json()["entries"]] == [
        (["notes"], "notes/state.md"),
        (["reports"], "reports/summary.md"),
    ]
    assert searched.status_code == 200
    assert searched.json()["entries"][0]["agent_ids"] == ["notes"]
    assert searched.json()["entries"][0]["path"] == "notes/state.md"
    assert searched.json()["entries"][0]["match_count"] == 1
    assert filtered.status_code == 200
    assert [entry["path"] for entry in filtered.json()["entries"]] == ["reports/summary.md"]


def test_global_files_merges_agents_sharing_the_same_filesystem(db, monkeypatch, client_factory):
    filesystem = FileSystem(db, namespace="shared")
    metadata = filesystem.write("state.md", "shared")
    client = client_factory(
        Agent(id="one", db=db, filesystem=filesystem),
        Agent(id="two", db=db, filesystem=filesystem),
    )
    # The route resolves a per-caller copy of the filesystem, so spy on the class:
    # one shared store must still be read once, not once per agent.
    list_files = AsyncMock(wraps=FileSystem.alist)
    search_files = AsyncMock(wraps=FileSystem.asearch)
    monkeypatch.setattr(FileSystem, "alist", lambda self, *a, **k: list_files(self, *a, **k))
    monkeypatch.setattr(FileSystem, "asearch", lambda self, *a, **k: search_files(self, *a, **k))

    response = client.get("/filesystem/files", headers=_headers("alice"))
    list_files.assert_awaited_once()
    searched = client.get("/filesystem/files", params={"query": "shared"}, headers=_headers("alice"))
    assert list_files.await_count == 2
    search_files.assert_awaited_once()
    assert searched.status_code == 200
    assert searched.json()["entries"][0]["agent_ids"] == ["one", "two"]
    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"]))

    assert response.status_code == 200
    assert response.json()["entries"] == [
        {
            "filesystem_id": "shared",
            "namespace": "shared",
            "path": "state.md",
            "agent_ids": ["one", "two"],
            "size_bytes": 6,
            "version": 1,
            "updated_at": metadata.updated_at,
            "user_id": None,
            "snippet": None,
            "line": None,
            "match_count": None,
        }
    ]
    assert config.status_code == 200
    assert config.json()["filesystem"]["namespaces"][0]["agents"] == [{"id": "one"}, {"id": "two"}]

    restricted = client.get("/filesystem/files", headers=_headers("alice", ["agents:one:read", "filesystem:read"]))
    assert restricted.status_code == 200
    assert restricted.json()["entries"][0]["agent_ids"] == ["one"]


def test_global_files_skips_remote_agents_but_explicit_requests_fail(db, client_factory, monkeypatch):
    # No server runs at the remote's URL: stub the one attribute AgentOS reads at
    # startup so the test never touches the network.
    monkeypatch.setattr(RemoteAgent, "db", property(lambda self: None))
    filesystem = FileSystem(db, namespace="notes")
    filesystem.write("state.md", "local")
    agent = Agent(id="notes", db=db, filesystem=filesystem)
    remote = RemoteAgent(base_url="http://localhost:9999", agent_id="remote")
    client = client_factory(agent, remote)

    listed = client.get("/filesystem/files", headers=_headers("alice"))
    explicit = client.get("/filesystem/files", params={"agent_id": "remote"}, headers=_headers("alice"))

    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["state.md"]
    assert explicit.status_code == 501


def test_global_files_rejects_empty_scopes(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)

    response = client.get("/filesystem/files", headers=_headers("alice", []))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path,params",
    [
        ("/filesystem/files", {}),
        ("/filesystem/entries", {"agent_id": "notes"}),
        ("/filesystem/content", {"agent_id": "notes", "path": "a.md"}),
        ("/filesystem/search", {"agent_id": "notes", "query": "x"}),
    ],
)
def test_filesystem_routes_require_filesystem_read(db, client_factory, path, params):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)
    assert agent.filesystem_instance is not None
    agent.filesystem_instance.write("a.md", "x\n")

    # Reading an agent is not reading its files.
    assert client.get(path, params=params, headers=_headers("alice", ["agents:read"])).status_code == 403
    # The files scope still needs access to the agent that holds them.
    assert client.get(path, params=params, headers=_headers("alice", ["filesystem:read"])).status_code == 403
    both = client.get(path, params=params, headers=_headers("alice", ["agents:notes:read", "filesystem:read"]))
    assert both.status_code == 200


@pytest.mark.parametrize("namespace", [None, "My Namespace", "Tenants/{user_id}/{agent_id}"])
def test_config_namespace_filters_global_files_for_the_caller(db, namespace, client_factory):
    configured_filesystem = FileSystem(db, namespace=namespace) if namespace else True
    agent = Agent(id="notes", db=db, filesystem=configured_filesystem)
    client = client_factory(agent, user_isolation=True)
    filesystem = agent.filesystem_instance
    assert filesystem is not None
    filesystem.resolve(user_id="Alice", agent_id="notes").write("state.md", "private")

    config = client.get("/config", headers=_headers("Alice", ["config:read", "agents:read"]))
    assert config.status_code == 200
    resolved_namespace = config.json()["filesystem"]["namespaces"][0]["namespace"]
    listed = client.get("/filesystem/files", params={"namespace": resolved_namespace}, headers=_headers("Alice"))

    assert listed.status_code == 200
    assert [(entry["namespace"], entry["path"]) for entry in listed.json()["entries"]] == [
        (resolved_namespace, "state.md")
    ]
    other_user = client.get("/filesystem/files", params={"namespace": resolved_namespace}, headers=_headers("alice"))
    assert other_user.status_code == 200
    assert other_user.json()["entries"] == []


def test_global_files_only_lists_agents_visible_to_the_caller(db, client_factory):
    notes = Agent(id="notes", db=db, filesystem=True)
    reports = Agent(id="reports", db=db, filesystem=True)
    client = client_factory(notes, reports)
    assert notes.filesystem_instance is not None
    notes.filesystem_instance.write("notes.md", "notes")
    assert reports.filesystem_instance is not None
    reports.filesystem_instance.write("reports.md", "reports")

    response = client.get(
        "/filesystem/files",
        headers=_headers("alice", ["agents:notes:read", "filesystem:read"]),
    )

    assert response.status_code == 200
    assert [entry["agent_ids"] for entry in response.json()["entries"]] == [["notes"]]


def test_managed_isolation_requires_authentication_and_separates_users(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent, user_isolation=True)
    filesystem = agent.filesystem_instance
    assert filesystem is not None
    filesystem.resolve(user_id="Alice").write("private.md", "upper")
    filesystem.resolve(user_id="alice").write("private.md", "lower")

    assert client.get("/filesystem/entries", params={"agent_id": "notes"}).status_code == 401

    upper = client.get(
        "/filesystem/content", params={"agent_id": "notes", "path": "private.md"}, headers=_headers("Alice")
    )
    lower = client.get(
        "/filesystem/content", params={"agent_id": "notes", "path": "private.md"}, headers=_headers("alice")
    )

    assert upper.status_code == 200
    assert lower.status_code == 200
    assert upper.json()["content"] == "upper"
    assert lower.json()["content"] == "lower"


def test_explicit_template_binds_user_and_agent_from_trusted_context(db, client_factory):
    filesystem = FileSystem(db, namespace="Tenants/{user_id}/Agents/{agent_id}")
    agent = Agent(id="notes", db=db, filesystem=filesystem)
    client = client_factory(agent, user_isolation=True)
    filesystem.resolve(user_id="Alice", agent_id="notes").write("state.md", "private")

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "state.md"},
        headers=_headers("Alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "private"


def test_unresolved_explicit_template_returns_400(db, client_factory):
    agent = Agent(
        id="notes",
        db=db,
        filesystem=FileSystem(db, namespace="teams/{team_id}/agents/{agent_id}"),
    )
    client = client_factory(agent)

    response = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_headers("alice"))

    assert response.status_code == 400
    assert "team_id" in response.text


def test_factory_agent_filesystem_is_browsable(db, client_factory):
    filesystem = FileSystem(db, namespace="factories/{agent_id}")
    filesystem.resolve(agent_id="factory-notes").write("state.md", "factory")
    factory = AgentFactory(
        id="factory-notes",
        db=db,
        factory=lambda ctx: Agent(id="factory-notes", db=db, filesystem=filesystem),
    )
    client = client_factory(factory)

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "factory-notes", "path": "state.md"},
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "factory"


def test_stored_agent_route_preserves_encoded_namespace_and_separate_db(tmp_path, client_factory):
    catalog_db = SqliteDb(id="catalog-db", db_file=str(tmp_path / "catalog.db"))
    files_db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    filesystem = FileSystem(files_db, namespace="My Namespace")
    filesystem.write("state.md", "separate")
    Agent(id="stored-notes", db=catalog_db, filesystem=filesystem).save()
    client = client_factory(db=catalog_db, registry=Registry(dbs=[files_db]))

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "stored-notes", "path": "state.md"},
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "separate"


def test_content_preview_has_a_continuation_offset(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)
    assert agent.filesystem_instance is not None
    agent.filesystem_instance.write("large.md", "abcdefghij")

    first = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "large.md", "limit": 4},
        headers=_headers("alice"),
    )
    second = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "large.md", "offset": first.json()["next_offset"], "limit": 4},
        headers=_headers("alice"),
    )

    assert first.status_code == 200
    assert first.json()["content"] == "abcd"
    assert first.json()["next_offset"] == 4
    assert second.status_code == 200
    assert second.json()["content"] == "efgh"
    assert second.json()["next_offset"] == 8


def test_config_describes_filesystem_at_os_level(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    factory = AgentFactory(
        id="factory-notes",
        db=db,
        factory=lambda ctx: Agent(id="factory-notes", db=db, filesystem=True),
    )
    client = client_factory(agent, factory, user_isolation=True)

    response = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"]))

    assert response.status_code == 200
    agents = {entry["id"]: entry for entry in response.json()["agents"]}
    assert response.json()["filesystem"] == {
        "namespaces": [
            {
                "backend_type": "db",
                "db_id": "filesystem-db",
                "table_name": "agno_fs",
                "namespace": "notes",
                "user_isolation": True,
                "max_file_bytes": 1_000_000,
                "max_namespace_bytes": 20_000_000,
                "id": "notes",
                "declared": False,
                "company": False,
                "agents": [{"id": "notes"}],
            }
        ]
    }
    assert "filesystem" not in agents["notes"]
    assert "filesystem" not in agents["factory-notes"]


def test_manual_read_only_toolkit_is_discovered_and_browsable(db, client_factory):
    shared = FileSystem(db, namespace="research/decisions")
    recorder = Agent(id="recorder", db=db, filesystem=shared)
    answerer = Agent(id="answerer", db=db, tools=[FileSystem(db, namespace="research/decisions").tools(read_only=True)])
    client = client_factory(recorder, answerer)
    shared.write("decisions.md", "vector db: pgvector\n")

    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()
    assert [(i["namespace"], i["agents"]) for i in config["filesystem"]["namespaces"]] == [
        ("research/decisions", [{"id": "answerer", "access": "read_only"}, {"id": "recorder"}])
    ]
    agents = client.get("/agents", headers=_headers("alice")).json()
    assert {entry["id"]: entry["filesystem"] for entry in agents} == {"recorder": True, "answerer": True}

    listed = client.get("/filesystem/entries", params={"agent_id": "answerer"}, headers=_headers("alice"))
    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["decisions.md"]

    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["path"], row["agent_ids"]) for row in rows] == [("decisions.md", ["answerer", "recorder"])]


def test_read_only_filesystem_is_reported_read_only(db, client_factory):
    agent = Agent(id="answerer", db=db, filesystem=FileSystem(db, namespace="research", read_only=True))
    client = client_factory(agent)

    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()
    instance = config["filesystem"]["namespaces"][0]
    assert instance["agents"] == [{"id": "answerer", "access": "read_only"}]


@pytest.mark.parametrize("read_only_first", [True, False])
def test_config_full_access_takes_precedence_on_shared_store(db, read_only_first, client_factory):
    shared = FileSystem(db, namespace="shared")
    reader = FileSystem(db, namespace="shared", read_only=True)
    attachments = [reader, shared] if read_only_first else [shared, reader]
    client = client_factory(Agent(id="analyst", db=db, filesystem=attachments))

    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()

    assert len(config["filesystem"]["namespaces"]) == 1
    assert config["filesystem"]["namespaces"][0]["agents"] == [{"id": "analyst"}]


def test_namespace_selects_among_an_agents_filesystems(db, client_factory):
    own = FileSystem(db, namespace="own")
    reference = FileSystem(db, namespace="reference")
    agent = Agent(
        id="analyst",
        db=db,
        tools=[
            own.tools(name="own_files", include_tools=["write_file", "append_file"]),
            reference.tools(read_only=True),
        ],
    )
    client = client_factory(agent)
    own.write("draft.md", "mine\n")
    reference.write("handbook.md", "shared\n")

    default = client.get("/filesystem/entries", params={"agent_id": "analyst"}, headers=_headers("alice")).json()
    assert [entry["path"] for entry in default["entries"]] == ["draft.md"]

    selected = client.get(
        "/filesystem/entries", params={"agent_id": "analyst", "namespace": "reference"}, headers=_headers("alice")
    )
    assert [entry["path"] for entry in selected.json()["entries"]] == ["handbook.md"]

    content = client.get(
        "/filesystem/content",
        params={"agent_id": "analyst", "namespace": "reference", "path": "handbook.md"},
        headers=_headers("alice"),
    )
    assert content.json()["content"] == "shared\n"

    missing = client.get(
        "/filesystem/entries", params={"agent_id": "analyst", "namespace": "someone-else"}, headers=_headers("alice")
    )
    assert missing.status_code == 404

    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["namespace"], row["path"]) for row in rows] == [("own", "draft.md"), ("reference", "handbook.md")]


def test_namespace_alone_addresses_a_filesystem_within_caller_access(db, client_factory):
    shared = FileSystem(db, namespace="research/decisions")
    private = FileSystem(db, namespace="private")
    recorder = Agent(id="recorder", db=db, filesystem=shared)
    answerer = Agent(id="answerer", db=db, filesystem=FileSystem(db, namespace="research/decisions", read_only=True))
    keeper = Agent(id="keeper", db=db, filesystem=private)
    client = client_factory(recorder, answerer, keeper)
    shared.write("decisions.md", "vector db: pgvector\n")
    private.write("secret.md", "hidden\n")

    listed = client.get("/filesystem/entries", params={"namespace": "research/decisions"}, headers=_headers("alice"))
    assert listed.status_code == 200
    assert listed.json()["namespace"] == "research/decisions"
    assert listed.json()["agent_ids"] == ["answerer", "recorder"]
    assert [entry["path"] for entry in listed.json()["entries"]] == ["decisions.md"]

    assert client.get("/filesystem/entries", headers=_headers("alice")).status_code == 400
    assert client.get("/filesystem/content", params={"namespace": "private", "path": "secret.md"}).status_code == 401

    # A caller scoped to one agent cannot reach a namespace only other agents hold.
    scoped = _headers("alice", ["agents:recorder:read", "filesystem:read"])
    allowed = client.get(
        "/filesystem/content", params={"namespace": "research/decisions", "path": "decisions.md"}, headers=scoped
    )
    assert allowed.status_code == 200
    assert allowed.json()["agent_ids"] == ["recorder"]
    hidden = client.get("/filesystem/content", params={"namespace": "private", "path": "secret.md"}, headers=scoped)
    assert hidden.status_code == 404
    forbidden = client.get("/filesystem/entries", params={"agent_id": "keeper"}, headers=scoped)
    assert forbidden.status_code == 403


def test_same_namespace_on_two_backends_needs_an_agent(tmp_path, db, client_factory):
    from agno.fs.local import LocalFileSystem

    in_db = FileSystem(db, namespace="notes")
    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "files")), namespace="notes")
    client = client_factory(
        Agent(id="db-agent", db=db, filesystem=in_db), Agent(id="disk-agent", db=db, filesystem=on_disk)
    )
    in_db.write("a.md", "db\n")
    on_disk.write("b.md", "disk\n")

    ambiguous = client.get("/filesystem/entries", params={"namespace": "notes"}, headers=_headers("alice"))
    assert ambiguous.status_code == 409

    chosen = client.get(
        "/filesystem/entries", params={"namespace": "notes", "agent_id": "disk-agent"}, headers=_headers("alice")
    )
    assert [entry["path"] for entry in chosen.json()["entries"]] == ["b.md"]


def test_shared_namespace_is_partitioned_per_user_under_isolation(db, client_factory):
    shared = FileSystem(db, namespace="research")
    recorder = Agent(id="recorder", db=db, filesystem=shared)
    client = client_factory(recorder, user_isolation=True)
    shared.resolve(user_id="alice").write("a.md", "alice's\n")
    shared.resolve(user_id="bob").write("a.md", "bob's\n")

    for user in ("alice", "bob"):
        content = client.get(
            "/filesystem/content", params={"namespace": "research", "path": "a.md"}, headers=_headers(user)
        )
        assert content.status_code == 200
        assert content.json()["content"] == f"{user}'s\n"
        assert content.json()["user_id"] == user
    listed = client.get("/filesystem/entries", params={"namespace": "research"}, headers=_headers("alice"))
    assert [(e["path"], e["user_id"]) for e in listed.json()["entries"]] == [("a.md", "alice")]
    rows = client.get("/filesystem/files", headers=_headers("bob")).json()["entries"]
    assert [(r["path"], r["user_id"]) for r in rows] == [("a.md", "bob")]

    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()
    assert config["filesystem"]["namespaces"][0]["user_isolation"] is True


def test_explicit_user_scoped_false_stays_shared_under_isolation(db, client_factory):
    handbook = FileSystem(db, namespace="handbook", user_scoped=False)
    reader = FileSystem(db, namespace="handbook", user_scoped=False, read_only=True)
    client = client_factory(Agent(id="reader", db=db, filesystem=reader), user_isolation=True)
    handbook.write("style.md", "shared\n")

    for user in ("alice", "bob"):
        content = client.get(
            "/filesystem/content", params={"namespace": "handbook", "path": "style.md"}, headers=_headers(user)
        )
        assert content.json()["content"] == "shared\n"
        assert content.json()["user_id"] is None
    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()
    assert config["filesystem"]["namespaces"][0]["user_isolation"] is False


def test_without_isolation_every_user_browses_the_shared_store(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)
    store = agent.filesystem_instance
    assert store is not None
    assert store.user_scoped is False
    store.write("shared.md", "everyone\n")

    for user in ("alice", "bob"):
        listed = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_headers(user))
        assert [(e["path"], e["user_id"]) for e in listed.json()["entries"]] == [("shared.md", None)]


def _admin_headers(user_id: str = "root") -> dict[str, str]:
    return _headers(user_id, ["agent_os:admin", "agents:read", "config:read"])


def test_admin_sees_every_partition_and_may_open_any(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent, user_isolation=True)
    store = agent.filesystem_instance
    assert store is not None and store.user_scoped is True
    store.partition(None).write("shared.md", "everyone\n")
    store.resolve(user_id="alice").write("notes/a.md", "alice\n")
    store.resolve(user_id="bob").write("notes/a.md", "bob\n")

    listed = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_admin_headers())
    assert listed.status_code == 200
    assert [(e["path"], e["type"], e["user_id"]) for e in listed.json()["entries"]] == [
        ("notes", "directory", None),
        ("shared.md", "file", None),
    ]
    assert listed.json()["usage"]["file_count"] == 3
    nested = client.get(
        "/filesystem/entries", params={"agent_id": "notes", "directory": "notes"}, headers=_admin_headers()
    )
    assert [(e["path"], e["user_id"]) for e in nested.json()["entries"]] == [
        ("notes/a.md", "alice"),
        ("notes/a.md", "bob"),
    ]

    content = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "notes/a.md", "user_id": "bob"},
        headers=_admin_headers(),
    )
    assert content.json()["content"] == "bob\n"
    shared = client.get(
        "/filesystem/content", params={"agent_id": "notes", "path": "shared.md"}, headers=_admin_headers()
    )
    assert shared.json()["content"] == "everyone\n"

    searched = client.get("/filesystem/search", params={"agent_id": "notes", "query": "bob"}, headers=_admin_headers())
    assert [(e["path"], e["user_id"]) for e in searched.json()["entries"]] == [("notes/a.md", "bob")]

    rows = client.get("/filesystem/files", headers=_admin_headers()).json()["entries"]
    assert [(r["path"], r["user_id"]) for r in rows] == [
        ("notes/a.md", "alice"),
        ("notes/a.md", "bob"),
        ("shared.md", None),
    ]


def test_a_user_may_name_only_their_own_partition(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent, user_isolation=True)
    store = agent.filesystem_instance
    assert store is not None
    store.resolve(user_id="alice").write("a.md", "alice\n")
    store.resolve(user_id="alice").write("drafts/b.md", "alice\n")
    store.resolve(user_id="bob").write("a.md", "bob\n")

    own = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "a.md", "user_id": "alice"},
        headers=_headers("alice"),
    )
    assert own.json()["content"] == "alice\n"
    other = client.get(
        "/filesystem/content", params={"agent_id": "notes", "path": "a.md", "user_id": "bob"}, headers=_headers("alice")
    )
    assert other.status_code == 403
    listed = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_headers("alice"))
    # A directory holding one user's files carries that owner, like its files.
    assert [(e["path"], e["user_id"]) for e in listed.json()["entries"]] == [("drafts", "alice"), ("a.md", "alice")]


@pytest.mark.parametrize(
    "scopes,expected",
    [
        (["agents:read"], 403),
        (["agents:read", "filesystem:read"], 200),
    ],
)
def test_service_account_tokens_need_filesystem_read(db, client_factory, scopes, expected):
    import time

    from agno.os.service_accounts import generate_token

    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent, db=db)
    assert agent.filesystem_instance is not None
    agent.filesystem_instance.write("a.md", "x\n")
    token, token_hash, token_prefix = generate_token()
    now = int(time.time())
    db.create_service_account(
        {
            "id": "sa-files",
            "name": "files-bot",
            "user_id": None,
            "token_hash": token_hash,
            "token_prefix": token_prefix,
            "scopes": scopes,
            "created_at": now,
            "expires_at": now + 3600,
            "last_used_at": None,
            "revoked_at": None,
            "created_by": None,
        }
    )

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "a.md"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == expected


def test_filesystem_scope_holds_for_other_methods_and_path_forms(db, client_factory):
    agent = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(agent)
    assert agent.filesystem_instance is not None
    agent.filesystem_instance.write("a.md", "secret\n")
    agent_only = _headers("alice", ["agents:read"])
    params = {"agent_id": "notes", "path": "a.md"}

    for path in ("/filesystem/content", "/filesystem/content/", "/filesystem/./content"):
        response = client.get(path, params=params, headers=agent_only)
        assert response.status_code in (403, 404), path
        assert "secret" not in response.text
    head = client.head("/filesystem/content", params=params, headers=agent_only)
    assert head.status_code in (403, 405)


def _unregistered_tool(query: str) -> str:
    """A tool the test registry does not hold."""
    return query


def test_a_stored_agent_with_unresolvable_tools_does_not_break_browsing(db, client_factory):
    from agno.models.openai import OpenAIResponses

    # Saved elsewhere with a tool this OS's registry cannot resolve.
    Agent(id="broken", name="Broken", model=OpenAIResponses(id="gpt-5.6-luna"), tools=[_unregistered_tool]).save(db=db)
    notes = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(notes, db=db, registry=Registry(dbs=[db]))
    assert notes.filesystem_instance is not None
    notes.filesystem_instance.write("a.md", "hello\n")

    listed = client.get("/filesystem/files", headers=_headers("alice"))
    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["a.md"]
    by_namespace = client.get("/filesystem/entries", params={"namespace": "notes"}, headers=_headers("alice"))
    assert by_namespace.status_code == 200


@pytest.mark.parametrize("enabled", [True, False])
def test_top_level_user_isolation_partitions_agent_filesystems(db, enabled):
    agent = Agent(id="notes", db=db, filesystem=True)
    AgentOS(
        id=OS_ID,
        agents=[agent],
        db=db,
        authorization=Authorization(verification_keys=[JWT_SECRET], algorithm="HS256"),
        user_isolation=enabled,
    ).get_app()

    assert agent.filesystem_instance is not None
    assert agent.filesystem_instance.user_scoped is enabled


# ---------------------------------------------------------------------------
# Filesystems declared on the AgentOS: AgentOS(filesystem=...)
# ---------------------------------------------------------------------------

FILES_ONLY = ["filesystem:read"]
ONE_FILESYSTEM_ROUTES = (
    ("/filesystem/entries", {}),
    ("/filesystem/content", {"path": "style.md"}),
    ("/filesystem/search", {"query": "needle"}),
)


@pytest.fixture
def archive_db(tmp_path):
    database = SqliteDb(id="archive-db", db_file=str(tmp_path / "archive.db"))
    try:
        yield database
    finally:
        database.db_engine.dispose()


def _declared_entry(namespace: str, **overrides) -> dict:
    return {
        "backend_type": "db",
        "db_id": "filesystem-db",
        "table_name": "agno_fs",
        "namespace": namespace,
        "user_isolation": False,
        "max_file_bytes": 1_000_000,
        "max_namespace_bytes": 20_000_000,
        "id": namespace,
        "declared": True,
        "company": False,
        "agents": [],
        **overrides,
    }


def _config_entries(client, headers=None) -> list[dict]:
    config = client.get("/config", headers=headers)
    assert config.status_code == 200
    return config.json()["filesystem"]["namespaces"]


def test_a_declared_filesystem_with_no_agent_is_listed_and_read_by_id(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "plain words needle\n")
    handbook.write("guides/tone.md", "short sentences\n")
    client = client_factory(db=db, filesystem=handbook)

    assert _config_entries(client, _headers("alice", ["config:read"])) == [_declared_entry("handbook")]

    files_only = _headers("alice", FILES_ONLY)
    by_id = {"filesystem_id": "handbook"}
    rows = client.get("/filesystem/files", params=by_id, headers=files_only)
    assert rows.status_code == 200
    assert [(row["filesystem_id"], row["path"], row["agent_ids"]) for row in rows.json()["entries"]] == [
        ("handbook", "guides/tone.md", []),
        ("handbook", "style.md", []),
    ]
    listed = client.get("/filesystem/entries", params=by_id, headers=files_only)
    assert listed.status_code == 200
    assert (listed.json()["filesystem_id"], listed.json()["namespace"], listed.json()["agent_ids"]) == (
        "handbook",
        "handbook",
        [],
    )
    assert [(entry["path"], entry["type"]) for entry in listed.json()["entries"]] == [
        ("guides", "directory"),
        ("style.md", "file"),
    ]
    content = client.get("/filesystem/content", params={**by_id, "path": "style.md"}, headers=files_only)
    assert content.status_code == 200
    assert content.json()["content"] == "plain words needle\n"
    assert content.json()["filesystem_id"] == "handbook"
    search = client.get("/filesystem/search", params={**by_id, "query": "needle"}, headers=files_only)
    assert search.status_code == 200
    assert search.json()["filesystem_id"] == "handbook"
    assert [entry["path"] for entry in search.json()["entries"]] == ["style.md"]

    # An id nothing uses is not found, and a request must still name something.
    assert client.get("/filesystem/entries", params={"filesystem_id": "missing"}, headers=files_only).status_code == 404
    assert client.get("/filesystem/entries", headers=files_only).status_code == 400
    assert client.get("/filesystem/entries", params={"filesystem_id": ""}, headers=files_only).status_code == 400


def test_an_os_with_only_a_filesystem_serves_it_without_authorization(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "plain words needle\n")
    client = client_factory(filesystem=[handbook], authorization=False)

    assert _config_entries(client) == [_declared_entry("handbook")]
    rows = client.get("/filesystem/files").json()["entries"]
    assert [(row["filesystem_id"], row["path"]) for row in rows] == [("handbook", "style.md")]
    for path, params in ONE_FILESYSTEM_ROUTES:
        by_id = client.get(path, params={"filesystem_id": "handbook", **params})
        assert by_id.status_code == 200, path
        # The namespace still addresses it, as the page on an older UI does.
        by_namespace = client.get(path, params={"namespace": "handbook", **params})
        assert by_namespace.status_code == 200, path
        assert by_namespace.json() == by_id.json()


def test_one_namespace_on_two_databases_gets_two_ids(db, archive_db, client_factory):
    current = FileSystem(db, namespace="handbook")
    archive = FileSystem(archive_db, namespace="handbook")
    client = client_factory(db=db, filesystem=[current, archive])
    current.write("style.md", "current needle\n")
    archive.write("style.md", "archive needle\n")

    entries = _config_entries(client, _headers("alice", ["config:read"]))
    assert [(entry["id"], entry["db_id"], entry["namespace"], entry["declared"]) for entry in entries] == [
        ("handbook:archive-db", "archive-db", "handbook", True),
        ("handbook:filesystem-db", "filesystem-db", "handbook", True),
    ]

    files_only = _headers("alice", FILES_ONLY)
    for filesystem_id, expected in (("handbook:filesystem-db", "current"), ("handbook:archive-db", "archive")):
        by_id = {"filesystem_id": filesystem_id}
        content = client.get("/filesystem/content", params={**by_id, "path": "style.md"}, headers=files_only)
        assert content.status_code == 200
        assert content.json()["content"] == f"{expected} needle\n"
        assert content.json()["filesystem_id"] == filesystem_id
        listed = client.get("/filesystem/entries", params=by_id, headers=files_only)
        assert [entry["path"] for entry in listed.json()["entries"]] == ["style.md"]
        search = client.get("/filesystem/search", params={**by_id, "query": "needle"}, headers=files_only)
        assert [entry["snippet"] for entry in search.json()["entries"]] == [f"{expected} needle\n"]
        rows = client.get("/filesystem/files", params=by_id, headers=files_only).json()["entries"]
        assert [(row["filesystem_id"], row["path"]) for row in rows] == [(filesystem_id, "style.md")]

    # Every row says which of the two it belongs to.
    rows = client.get("/filesystem/files", headers=files_only).json()["entries"]
    assert [(row["filesystem_id"], row["namespace"]) for row in rows] == [
        ("handbook:archive-db", "handbook"),
        ("handbook:filesystem-db", "handbook"),
    ]
    # The bare namespace names neither store, as an id or as a namespace.
    for params in ({"filesystem_id": "handbook"}, {"namespace": "handbook"}):
        ambiguous = client.get("/filesystem/content", params={**params, "path": "style.md"}, headers=files_only)
        assert ambiguous.status_code == 409, params
        assert "needle" not in ambiguous.text


def test_one_namespace_on_two_tables_of_one_database_gets_two_ids(db, client_factory):
    from agno.fs.db import DbFileSystem

    default_table = FileSystem(db, namespace="handbook")
    other_table = FileSystem(backend=DbFileSystem(db=db, table_name="other_files"), namespace="handbook")
    client = client_factory(db=db, filesystem=[default_table, other_table])
    default_table.write("style.md", "default\n")
    other_table.write("style.md", "other\n")

    ids = [entry["id"] for entry in _config_entries(client, _headers("alice", ["config:read"]))]
    assert sorted(ids) == ["handbook:filesystem-db:agno_fs", "handbook:filesystem-db:other_files"]
    for filesystem_id, expected in zip(sorted(ids), ("default\n", "other\n")):
        content = client.get(
            "/filesystem/content",
            params={"filesystem_id": filesystem_id, "path": "style.md"},
            headers=_headers("alice", FILES_ONLY),
        )
        assert content.json()["content"] == expected


def test_a_declared_filesystem_on_a_local_folder_is_listed_and_browsable(tmp_path, db, client_factory):
    from agno.fs.local import LocalFileSystem

    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "team-files")), namespace="handbook")
    on_disk.write("style.md", "on disk needle\n")
    client = client_factory(db=db, filesystem=on_disk)

    entries = _config_entries(client, _headers("alice", ["config:read"]))
    assert [(entry["id"], entry["backend_type"], entry["declared"], entry["agents"]) for entry in entries] == [
        ("handbook", "local", True, [])
    ]
    # Neither the listing nor an id carries the folder's path on the server.
    assert str(tmp_path) not in str(entries)
    for path, params in ONE_FILESYSTEM_ROUTES:
        response = client.get(
            path, params={"filesystem_id": "handbook", **params}, headers=_headers("alice", FILES_ONLY)
        )
        assert response.status_code == 200, path
    content = client.get(
        "/filesystem/content",
        params={"filesystem_id": "handbook", "path": "style.md"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert content.json()["content"] == "on disk needle\n"


@pytest.mark.parametrize("namespace", ["scratch/{agent_id}", "teams/{team_id}/notes", "{user_id}/{agent_id}"])
def test_a_declared_namespace_only_an_agent_can_fill_starts_and_has_no_entry_until_one_holds_it(
    db, namespace, client_factory
):
    template = FileSystem(db, namespace=namespace)
    client = client_factory(db=db, filesystem=[template, FileSystem(db, namespace="handbook")])

    headers = _headers("alice", ["config:read", "agents:read"])
    assert [entry["id"] for entry in _config_entries(client, headers)] == ["handbook"]
    rows = client.get("/filesystem/files", headers=_headers("alice"))
    assert rows.status_code == 200
    assert rows.json()["entries"] == []


def test_a_declared_agent_namespace_is_listed_once_an_agent_holds_it(db, client_factory):
    template = FileSystem(db, namespace="scratch/{agent_id}")
    client = client_factory(Agent(id="writer", db=db, filesystem=template), db=db, filesystem=template)
    template.resolve(agent_id="writer").write("draft.md", "draft\n")

    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert [(entry["id"], entry["declared"], entry["agents"]) for entry in entries] == [
        ("scratch/writer", False, [{"id": "writer"}])
    ]
    content = client.get(
        "/filesystem/content", params={"filesystem_id": "scratch/writer", "path": "draft.md"}, headers=_headers("alice")
    )
    assert content.json()["content"] == "draft\n"
    assert content.json()["agent_ids"] == ["writer"]
    # It is the agent's store, so it needs access to the agent.
    hidden = client.get(
        "/filesystem/content",
        params={"filesystem_id": "scratch/writer", "path": "draft.md"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert hidden.status_code == 403


def _failing_factory(db) -> AgentFactory:
    def build(ctx):
        raise RuntimeError("this agent cannot be built")

    return AgentFactory(id="broken", db=db, factory=build)


def test_a_request_for_a_declared_filesystem_loads_no_agent(db, client_factory, monkeypatch):
    from agno.os.routers.filesystem import router as filesystem_router

    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "plain words needle\n")
    client = client_factory(_failing_factory(db), Agent(id="notes", db=db, filesystem=True), db=db, filesystem=handbook)
    resolved: list[str] = []
    resolve_agent = filesystem_router.resolve_agent

    async def spy(agent_id, *args, **kwargs):
        resolved.append(agent_id)
        return await resolve_agent(agent_id, *args, **kwargs)

    monkeypatch.setattr(filesystem_router, "resolve_agent", spy)

    for path, params in (("/filesystem/files", {}), *ONE_FILESYSTEM_ROUTES):
        response = client.get(path, params={"filesystem_id": "handbook", **params}, headers=_headers("alice"))
        assert response.status_code == 200, path
    assert resolved == []

    # Every other request reads the agents, and one that cannot be built does not hide the declared filesystem.
    assert client.get("/filesystem/files", headers=_headers("alice")).status_code == 200
    by_namespace = client.get("/filesystem/entries", params={"namespace": "handbook"}, headers=_headers("alice"))
    assert by_namespace.status_code == 200
    assert "broken" in resolved


def test_filesystem_read_alone_reads_a_declared_filesystem_and_no_agent_filesystem(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    private = FileSystem(db, namespace="private")
    client = client_factory(Agent(id="keeper", db=db, filesystem=private), db=db, filesystem=handbook)
    handbook.write("style.md", "shared needle\n")
    private.write("style.md", "hidden needle\n")
    files_only = _headers("alice", FILES_ONLY)

    rows = client.get("/filesystem/files", headers=files_only)
    assert rows.status_code == 200
    assert [(row["filesystem_id"], row["path"], row["agent_ids"]) for row in rows.json()["entries"]] == [
        ("handbook", "style.md", [])
    ]
    for path, params in ONE_FILESYSTEM_ROUTES:
        allowed = client.get(path, params={"filesystem_id": "handbook", **params}, headers=files_only)
        assert allowed.status_code == 200, path
        # The agent's filesystem stays behind access to the agent: not found by id or by namespace.
        for selector in ({"filesystem_id": "private"}, {"namespace": "private"}):
            hidden = client.get(path, params={**selector, **params}, headers=files_only)
            assert hidden.status_code == 404, (path, selector)
            assert "hidden" not in hidden.text
        by_agent = client.get(path, params={"agent_id": "keeper", **params}, headers=files_only)
        assert by_agent.status_code == 403, path
    assert client.get("/filesystem/files", params={"agent_id": "keeper"}, headers=files_only).status_code == 403
    assert (
        client.get("/filesystem/files", params={"filesystem_id": "private"}, headers=files_only).json()["entries"] == []
    )

    # A declared filesystem still needs filesystem:read.
    for scopes in (["agents:read"], ["config:read"], []):
        refused = client.get(
            "/filesystem/content",
            params={"filesystem_id": "handbook", "path": "style.md"},
            headers=_headers("alice", scopes),
        )
        assert refused.status_code == 403, scopes
        assert client.get("/filesystem/files", headers=_headers("alice", scopes)).status_code == 403, scopes
    # A caller who reads the agent sees both.
    both = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["filesystem_id"], row["agent_ids"]) for row in both] == [("handbook", []), ("private", ["keeper"])]
    private_by_id = client.get(
        "/filesystem/content", params={"filesystem_id": "private", "path": "style.md"}, headers=_headers("alice")
    )
    assert private_by_id.json()["content"] == "hidden needle\n"
    assert private_by_id.json()["agent_ids"] == ["keeper"]
    # Naming an agent asks for that agent's filesystems only.
    of_agent = client.get("/filesystem/files", params={"agent_id": "keeper"}, headers=_headers("alice")).json()[
        "entries"
    ]
    assert [row["filesystem_id"] for row in of_agent] == ["private"]
    first_of_agent = client.get("/filesystem/entries", params={"agent_id": "keeper"}, headers=_headers("alice"))
    assert first_of_agent.json()["filesystem_id"] == "private"


def test_without_a_declared_filesystem_a_caller_with_no_agent_is_refused_as_before(db, client_factory):
    client = client_factory(Agent(id="keeper", db=db, filesystem=FileSystem(db, namespace="private")), db=db)
    files_only = _headers("alice", FILES_ONLY)

    assert client.get("/filesystem/files", headers=files_only).status_code == 403
    for selector in ({"filesystem_id": "private"}, {"namespace": "private"}):
        assert client.get("/filesystem/entries", params=selector, headers=files_only).status_code == 403, selector


def test_config_lists_declared_filesystems_to_a_caller_without_agent_access(db, client_factory):
    client = client_factory(
        Agent(id="keeper", db=db, filesystem=FileSystem(db, namespace="private")),
        db=db,
        filesystem=[FileSystem(db, namespace="handbook")],
    )

    without_agents = _config_entries(client, _headers("alice", ["config:read"]))
    assert [(entry["id"], entry["declared"], entry["agents"]) for entry in without_agents] == [("handbook", True, [])]
    with_agents = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert [(entry["id"], entry["declared"], entry["agents"]) for entry in with_agents] == [
        ("handbook", True, []),
        ("private", False, [{"id": "keeper"}]),
    ]


@pytest.mark.parametrize("same_object", [True, False])
def test_a_store_declared_and_held_by_an_agent_is_one_entry(db, same_object, client_factory, monkeypatch):
    handbook = FileSystem(db, namespace="handbook")
    held_by_agent = handbook if same_object else FileSystem(db, namespace="handbook", read_only=True)
    client = client_factory(Agent(id="writer", db=db, filesystem=held_by_agent), db=db, filesystem=[handbook])
    handbook.write("style.md", "shared\n")
    access = {"id": "writer"} if same_object else {"id": "writer", "access": "read_only"}

    with_agents = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert with_agents == [_declared_entry("handbook", agents=[access])]
    # A caller who cannot read the agent is not told who else holds the store.
    assert _config_entries(client, _headers("alice", ["config:read"])) == [_declared_entry("handbook")]

    list_files = AsyncMock(wraps=FileSystem.alist)
    monkeypatch.setattr(FileSystem, "alist", lambda self, *a, **k: list_files(self, *a, **k))
    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["filesystem_id"], row["path"], row["agent_ids"]) for row in rows] == [
        ("handbook", "style.md", ["writer"])
    ]
    list_files.assert_awaited_once()
    files_only = client.get("/filesystem/files", headers=_headers("alice", FILES_ONLY)).json()["entries"]
    assert [(row["path"], row["agent_ids"]) for row in files_only] == [("style.md", [])]
    # Through the agent it is the same store under the same id.
    by_agent = client.get("/filesystem/entries", params={"agent_id": "writer"}, headers=_headers("alice"))
    assert (by_agent.json()["filesystem_id"], by_agent.json()["agent_ids"]) == ("handbook", ["writer"])


def test_an_agent_with_other_limits_joins_the_entry_of_the_store(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    smaller = FileSystem(db, namespace="handbook", max_namespace_bytes=5_000_000)
    client = client_factory(Agent(id="writer", db=db, filesystem=smaller), db=db, filesystem=[handbook])

    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))

    assert entries == [_declared_entry("handbook", agents=[{"id": "writer"}])]


@pytest.mark.parametrize("smaller_first", [True, False])
def test_two_agents_with_other_limits_on_one_store_share_one_entry(db, smaller_first, client_factory):
    larger = Agent(id="zed", db=db, filesystem=FileSystem(db, namespace="notes"))
    smaller = Agent(id="abe", db=db, filesystem=FileSystem(db, namespace="notes", max_namespace_bytes=5_000_000))
    # The order the agents are passed in does not choose the limits.
    client = client_factory(*([smaller, larger] if smaller_first else [larger, smaller]))
    headers = _headers("alice", ["config:read", "agents:read", "filesystem:read"])

    entries = _config_entries(client, headers)
    assert [(entry["id"], entry["agents"]) for entry in entries] == [("notes", [{"id": "abe"}, {"id": "zed"}])]
    # The entry shows the limits of the first agent by id, and so does a request for the store.
    assert entries[0]["max_namespace_bytes"] == 5_000_000
    listed = client.get("/filesystem/entries", params={"filesystem_id": "notes"}, headers=headers)
    assert listed.json()["usage"]["bytes_limit"] == 5_000_000

    # A caller who reads one of the two agents sees the limits of that agent.
    only_zed = _headers("alice", ["config:read", "agents:zed:read", "filesystem:read"])
    assert [(e["agents"], e["max_namespace_bytes"]) for e in _config_entries(client, only_zed)] == [
        ([{"id": "zed"}], 20_000_000)
    ]
    listed = client.get("/filesystem/entries", params={"filesystem_id": "notes"}, headers=only_zed)
    assert listed.json()["usage"]["bytes_limit"] == 20_000_000


def test_a_declared_namespace_keeps_its_id_when_an_agent_uses_it_on_another_backend(tmp_path, db, client_factory):
    from agno.fs.local import LocalFileSystem

    declared = FileSystem(db, namespace="notes")
    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "files")), namespace="notes")
    client = client_factory(Agent(id="disk-agent", db=db, filesystem=on_disk), db=db, filesystem=declared)
    declared.write("style.md", "declared\n")
    on_disk.write("style.md", "disk\n")

    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    ids = {entry["backend_type"]: (entry["id"], entry["declared"]) for entry in entries}
    assert ids == {"db": ("notes", True), "local": ("notes:files", False)}

    for filesystem_id, expected, holders in (("notes", "declared\n", []), ("notes:files", "disk\n", ["disk-agent"])):
        content = client.get(
            "/filesystem/content",
            params={"filesystem_id": filesystem_id, "path": "style.md"},
            headers=_headers("alice"),
        )
        assert content.status_code == 200
        assert (content.json()["content"], content.json()["agent_ids"]) == (expected, holders)
    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["filesystem_id"], row["agent_ids"]) for row in rows] == [
        ("notes", []),
        ("notes:files", ["disk-agent"]),
    ]

    # The namespace alone names two stores, so it never opens one of them blind.
    for path, params in ONE_FILESYSTEM_ROUTES:
        by_namespace = client.get(path, params={"namespace": "notes", **params}, headers=_headers("alice"))
        assert by_namespace.status_code == 409, path
        assert "filesystem_id" in by_namespace.json()["detail"]
    by_agent = client.get(
        "/filesystem/content",
        params={"namespace": "notes", "agent_id": "disk-agent", "path": "style.md"},
        headers=_headers("alice"),
    )
    assert by_agent.json()["content"] == "disk\n"
    # A caller who reads no agent sees one store under the name.
    files_only = client.get(
        "/filesystem/content", params={"namespace": "notes", "path": "style.md"}, headers=_headers("alice", FILES_ONLY)
    )
    assert files_only.json()["content"] == "declared\n"


def test_two_agents_on_one_namespace_and_two_backends_are_read_by_id(tmp_path, db, client_factory):
    from agno.fs.local import LocalFileSystem

    in_db = FileSystem(db, namespace="notes")
    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "files")), namespace="notes")
    client = client_factory(
        Agent(id="db-agent", db=db, filesystem=in_db), Agent(id="disk-agent", db=db, filesystem=on_disk)
    )
    in_db.write("a.md", "db\n")
    on_disk.write("b.md", "disk\n")

    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert sorted(entry["id"] for entry in entries) == ["notes:files", "notes:filesystem-db"]
    for filesystem_id, expected in (("notes:filesystem-db", "a.md"), ("notes:files", "b.md")):
        listed = client.get("/filesystem/entries", params={"filesystem_id": filesystem_id}, headers=_headers("alice"))
        assert listed.status_code == 200
        assert [entry["path"] for entry in listed.json()["entries"]] == [expected]
    for path in ("/filesystem/entries", "/filesystem/files"):
        ambiguous = client.get(path, params={"filesystem_id": "notes"}, headers=_headers("alice"))
        assert ambiguous.status_code == 409, path
        assert "/filesystem/namespaces" in ambiguous.json()["detail"]


def test_a_longer_form_of_an_id_names_the_same_filesystem(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "shared\n")
    client = client_factory(db=db, filesystem=handbook)

    for filesystem_id in ("handbook", "handbook:filesystem-db", "handbook:filesystem-db:agno_fs"):
        content = client.get(
            "/filesystem/content",
            params={"filesystem_id": filesystem_id, "path": "style.md"},
            headers=_headers("alice", FILES_ONLY),
        )
        assert content.status_code == 200, filesystem_id
        # The response carries the id /config lists.
        assert content.json()["filesystem_id"] == "handbook"
    other_backend = client.get(
        "/filesystem/content",
        params={"filesystem_id": "handbook:archive-db", "path": "style.md"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert other_backend.status_code == 404


def test_filesystem_id_and_namespace_must_name_the_same_filesystem(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "shared\n")
    client = client_factory(db=db, filesystem=[handbook, FileSystem(db, namespace="drafts")])
    files_only = _headers("alice", FILES_ONLY)

    agree = client.get(
        "/filesystem/entries", params={"filesystem_id": "handbook", "namespace": "handbook"}, headers=files_only
    )
    assert agree.status_code == 200
    disagree = client.get(
        "/filesystem/entries", params={"filesystem_id": "handbook", "namespace": "drafts"}, headers=files_only
    )
    assert disagree.status_code == 404


@pytest.mark.parametrize("user_scoped", [None, True])
def test_a_declared_filesystem_is_partitioned_by_user_under_isolation(db, user_scoped, client_factory):
    handbook = FileSystem(db, namespace="handbook", user_scoped=user_scoped)
    client = client_factory(db=db, filesystem=handbook, user_isolation=True)
    # Left unset, the store follows the isolation setting of the OS. The declared object is as it was.
    assert handbook.user_scoped is user_scoped
    handbook.resolve(user_id="alice").write("a.md", "alice's\n")
    handbook.resolve(user_id="bob").write("a.md", "bob's\n")

    for user in ("alice", "bob"):
        headers = _headers(user, FILES_ONLY)
        by_id = {"filesystem_id": "handbook"}
        content = client.get("/filesystem/content", params={**by_id, "path": "a.md"}, headers=headers)
        assert content.status_code == 200
        assert (content.json()["content"], content.json()["user_id"]) == (f"{user}'s\n", user)
        listed = client.get("/filesystem/entries", params=by_id, headers=headers)
        assert [(e["path"], e["user_id"]) for e in listed.json()["entries"]] == [("a.md", user)]
        rows = client.get("/filesystem/files", headers=headers).json()["entries"]
        assert [(r["path"], r["user_id"]) for r in rows] == [("a.md", user)]
        searched = client.get("/filesystem/search", params={**by_id, "query": "s"}, headers=headers)
        assert [(e["path"], e["user_id"]) for e in searched.json()["entries"]] == [("a.md", user)]

    other = client.get(
        "/filesystem/content",
        params={"filesystem_id": "handbook", "path": "a.md", "user_id": "bob"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert other.status_code == 403
    assert "bob's" not in other.text
    assert _config_entries(client, _headers("alice", ["config:read"]))[0]["user_isolation"] is True
    every_partition = client.get(
        "/filesystem/files", headers=_headers("root", ["agent_os:admin", "filesystem:read"])
    ).json()["entries"]
    assert [(r["path"], r["user_id"]) for r in every_partition] == [("a.md", "alice"), ("a.md", "bob")]


def test_a_declared_filesystem_with_user_scoped_false_stays_shared_under_isolation(db, client_factory):
    handbook = FileSystem(db, namespace="handbook", user_scoped=False)
    client = client_factory(db=db, filesystem=handbook, user_isolation=True)
    handbook.write("style.md", "shared\n")

    assert handbook.user_scoped is False
    assert _config_entries(client, _headers("alice", ["config:read"]))[0]["user_isolation"] is False
    for user in ("alice", "bob"):
        content = client.get(
            "/filesystem/content",
            params={"filesystem_id": "handbook", "path": "style.md"},
            headers=_headers(user, FILES_ONLY),
        )
        assert (content.json()["content"], content.json()["user_id"]) == ("shared\n", None)


def test_a_declared_filesystem_stays_shared_without_isolation(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    client = client_factory(db=db, filesystem=handbook)
    handbook.write("style.md", "shared\n")

    assert _config_entries(client, _headers("alice", ["config:read"]))[0]["user_isolation"] is False
    for user in ("alice", "bob"):
        content = client.get(
            "/filesystem/content",
            params={"filesystem_id": "handbook", "path": "style.md"},
            headers=_headers(user, FILES_ONLY),
        )
        assert (content.json()["content"], content.json()["user_id"]) == ("shared\n", None)
    assert handbook.user_scoped is None


def test_a_declared_user_namespace_resolves_for_each_caller(db, client_factory):
    journals = FileSystem(db, namespace="journals/{user_id}")
    client = client_factory(db=db, filesystem=journals, user_isolation=True)
    journals.resolve(user_id="alice").write("today.md", "alice's\n")
    journals.resolve(user_id="bob").write("today.md", "bob's\n")

    entries = _config_entries(client, _headers("alice", ["config:read"]))
    assert [(entry["id"], entry["namespace"], entry["user_isolation"]) for entry in entries] == [
        ("journals/alice", "journals/alice", True)
    ]
    own = client.get(
        "/filesystem/content",
        params={"filesystem_id": "journals/alice", "path": "today.md"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert own.json()["content"] == "alice's\n"
    # Another user's namespace is not a filesystem of this caller.
    other = client.get(
        "/filesystem/content",
        params={"filesystem_id": "journals/bob", "path": "today.md"},
        headers=_headers("alice", FILES_ONLY),
    )
    assert other.status_code == 404
    rows = client.get("/filesystem/files", headers=_headers("bob", FILES_ONLY)).json()["entries"]
    assert [(row["filesystem_id"], row["path"]) for row in rows] == [("journals/bob", "today.md")]


@pytest.mark.parametrize(
    "namespace,user_scoped,reason",
    [("notes", True, "no user_id"), ("journals/{user_id}", None, "require user_id")],
)
def test_a_declared_filesystem_tells_a_caller_with_no_user_why_it_is_not_served(
    db, namespace, user_scoped, reason, client_factory
):
    scoped = FileSystem(db, namespace=namespace, user_scoped=user_scoped)
    client = client_factory(db=db, filesystem=scoped, authorization=False)

    # With no identity the namespace is listed as declared, placeholders included.
    assert [entry["id"] for entry in _config_entries(client)] == [namespace]
    for path, params in ONE_FILESYSTEM_ROUTES:
        for selector in ({"filesystem_id": namespace}, {"namespace": namespace}):
            refused = client.get(path, params={**selector, **params})
            assert refused.status_code == 400, (path, selector)
            assert reason in refused.json()["detail"]
    assert client.get("/filesystem/files", params={"filesystem_id": namespace}).status_code == 400
    # Another id is still not found, and the listing leaves the store out.
    assert client.get("/filesystem/entries", params={"filesystem_id": "missing"}).status_code == 404
    assert client.get("/filesystem/files").json()["entries"] == []


def test_an_empty_agent_id_names_no_agent(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    client = client_factory(
        Agent(id="plain", db=db), Agent(id="keeper", db=db, filesystem=True), db=db, filesystem=handbook
    )
    handbook.write("style.md", "shared\n")

    for params in ({}, {"agent_id": ""}, {"filesystem_id": ""}):
        rows = client.get("/filesystem/files", params=params, headers=_headers("alice"))
        assert rows.status_code == 200, params
        assert [(row["namespace"], row["path"]) for row in rows.json()["entries"]] == [("handbook", "style.md")]
        for selector in ({"filesystem_id": "handbook"}, {"namespace": "handbook"}):
            listed = client.get("/filesystem/entries", params={**params, **selector}, headers=_headers("alice"))
            assert listed.status_code == 200, (params, selector)
        assert client.get("/filesystem/entries", params=params, headers=_headers("alice")).status_code == 400


def test_a_caller_whose_id_cannot_be_part_of_a_namespace_does_not_see_that_filesystem(db, client_factory):
    journals = FileSystem(db, namespace="journals/{user_id}")
    client = client_factory(db=db, filesystem=[journals, FileSystem(db, namespace="handbook")])

    # A user id with a slash is not one path segment, so it fills no namespace.
    entries = _config_entries(client, _headers("team/alice", ["config:read"]))
    assert [entry["id"] for entry in entries] == ["handbook"]
    rows = client.get("/filesystem/files", headers=_headers("team/alice", FILES_ONLY))
    assert rows.status_code == 200
    listed = client.get(
        "/filesystem/entries", params={"filesystem_id": "handbook"}, headers=_headers("team/alice", FILES_ONLY)
    )
    assert listed.status_code == 200


def test_one_store_declared_twice_is_one_filesystem_described_by_the_first(db, client_factory):
    first = FileSystem(db, namespace="handbook", max_namespace_bytes=5_000_000)
    second = FileSystem(db, namespace="handbook", read_only=True)
    client = client_factory(db=db, filesystem=[first, second])

    entries = _config_entries(client, _headers("alice", ["config:read"]))
    assert entries == [_declared_entry("handbook", max_namespace_bytes=5_000_000)]
    listed = client.get(
        "/filesystem/entries", params={"filesystem_id": "handbook"}, headers=_headers("alice", FILES_ONLY)
    )
    assert listed.json()["usage"]["bytes_limit"] == 5_000_000


@pytest.mark.parametrize("enabled", [True, False])
def test_a_filesystem_declared_after_start_follows_the_isolation_setting(db, enabled):
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        authorization=Authorization(verification_keys=[JWT_SECRET], algorithm="HS256"),
        user_isolation=enabled,
    )
    app = agent_os.get_app()
    later = FileSystem(db, namespace="later")
    agent_os.filesystems.append(later)

    agent_os.resync(app)

    with TestClient(app, raise_server_exceptions=False) as client:
        entries = _config_entries(client, _headers("alice", ["config:read"]))
    assert [(entry["id"], entry["user_isolation"]) for entry in entries] == [("later", enabled)]
    assert later.user_scoped is None


def test_filesystem_routes_are_read_only(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    client = client_factory(db=db, filesystem=handbook)
    handbook.write("style.md", "shared\n")

    paths = {path: set(item) for path, item in client.app.openapi()["paths"].items() if "filesystem" in path}
    assert paths == {
        "/filesystem/content": {"get"},
        "/filesystem/entries": {"get"},
        "/filesystem/files": {"get"},
        "/filesystem/namespaces": {"get"},
        "/filesystem/search": {"get"},
    }
    admin = _headers("root", ["agent_os:admin"])
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(
            "/filesystem/content", params={"filesystem_id": "handbook", "path": "style.md"}, headers=admin
        )
        assert response.status_code == 405, method
    assert handbook.read("style.md") == "shared\n"


def test_declaring_a_filesystem_gives_no_agent_a_file_tool(db):
    plain = Agent(id="plain", db=db)
    AgentOS(id=OS_ID, db=db, agents=[plain], filesystem=FileSystem(db, namespace="handbook"))

    assert plain.filesystem is None
    assert plain.filesystems == []


def test_agent_filesystem_true_keeps_its_own_namespace_beside_a_declared_one(db, client_factory):
    notes = Agent(id="notes", db=db, filesystem=True)
    client = client_factory(notes, db=db, filesystem=FileSystem(db, namespace="handbook"))

    assert notes.filesystem_instance is not None
    assert notes.filesystem_instance.namespace == "notes"
    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert [(entry["id"], entry["declared"]) for entry in entries] == [("handbook", True), ("notes", False)]


def test_agentos_takes_one_filesystem_or_a_list_and_refuses_other_objects(db):
    handbook = FileSystem(db, namespace="handbook")
    drafts = FileSystem(db, namespace="drafts")

    assert AgentOS(id=OS_ID, db=db, filesystem=handbook).filesystems == [handbook]
    assert AgentOS(id=OS_ID, db=db, filesystem=[handbook, drafts]).filesystems == [handbook, drafts]
    assert AgentOS(id=OS_ID, db=db).filesystems == []
    # A filesystem alone is enough to start an OS.
    assert AgentOS(id=OS_ID, filesystem=handbook).filesystems == [handbook]

    for refused in (db, True, [handbook, "handbook"]):
        with pytest.raises(TypeError, match="FileSystem"):
            AgentOS(id=OS_ID, db=db, filesystem=refused)
    with pytest.raises(ValueError, match="a filesystem or a database must be provided"):
        AgentOS(id=OS_ID)


def test_filesystem_does_not_shift_positional_constructor_arguments():
    import inspect

    parameters = list(inspect.signature(AgentOS.__init__).parameters)
    # Every parameter that was there keeps its place: the new one comes after the last of them.
    assert parameters[parameters.index("knowledge") + 1] == "interfaces"
    assert parameters.index("filesystem") > parameters.index("company")


def test_declaring_a_filesystem_adds_no_database_to_the_os(db, archive_db, client_factory):
    archive = FileSystem(archive_db, namespace="handbook")
    archive.write("style.md", "archived\n")
    client = client_factory(Agent(id="plain", db=db), db=db, filesystem=archive)
    headers = _headers("alice", ["config:read", "sessions:read", "filesystem:read"])

    config = client.get("/config", headers=headers).json()
    assert config["databases"] == ["filesystem-db"]
    assert [entry["db_id"] for entry in config["session"]["dbs"]] == ["filesystem-db"]
    # A route that picks a database still finds the only one, with no db_id.
    assert client.get("/sessions", params={"type": "agent"}, headers=headers).status_code == 200
    # The file system is listed and read all the same.
    assert [(entry["id"], entry["db_id"]) for entry in config["filesystem"]["namespaces"]] == [
        ("handbook", "archive-db")
    ]
    content = client.get(
        "/filesystem/content", params={"filesystem_id": "handbook", "path": "style.md"}, headers=headers
    )
    assert content.json()["content"] == "archived\n"


def test_config_from_an_agentos_that_sends_no_filesystem_id_is_still_read():
    from agno.os.schema import ConfigResponse

    # The filesystem section as an AgentOS without ids sends it.
    entry = {
        "backend_type": "db",
        "db_id": "filesystem-db",
        "table_name": "agno_fs",
        "namespace": "notes",
        "user_isolation": False,
        "max_file_bytes": 1_000_000,
        "max_namespace_bytes": 20_000_000,
        "agents": [{"id": "notes"}],
    }
    config = ConfigResponse.model_validate(
        {
            "os_id": OS_ID,
            "databases": [],
            "agents": [],
            "teams": [],
            "workflows": [],
            "interfaces": [],
            "filesystem": {"namespaces": [entry]},
        }
    )

    assert config.filesystem is not None
    parsed = config.filesystem.namespaces[0]
    # Its namespace names the filesystem, and nothing there is declared.
    assert (parsed.id, parsed.declared) == ("notes", False)


# ---------------------------------------------------------------------------
# Filesystem ids
# ---------------------------------------------------------------------------


class _MemoryBackend:
    """Stands in for a backend that is neither a database table nor a folder."""


def test_id_forms_go_from_the_namespace_to_the_table_or_folder(tmp_path, db):
    from agno.db.postgres import PostgresDb
    from agno.fs._paths import NAMESPACE_SAFE
    from agno.fs.db import DbFileSystem
    from agno.fs.local import LocalFileSystem
    from agno.os.routers.filesystem.utils import _ID_SEPARATOR, _filesystem_id_forms

    forms = _filesystem_id_forms(FileSystem(db, namespace="handbook"))
    assert forms[:3] == (
        "handbook",
        "handbook:filesystem-db",
        "handbook:filesystem-db:agno_fs",
    )
    # The last form adds a digest of the database, never its path.
    assert len(forms) == 4 and forms[3].startswith("handbook:filesystem-db:agno_fs:") and "/" not in forms[3]
    from_engine = FileSystem(backend=DbFileSystem(db_engine=db.db_engine, table_name="files"), namespace="handbook")
    assert _filesystem_id_forms(from_engine)[:3] == ("handbook", "handbook:db", "handbook:db:files")
    on_disk = _filesystem_id_forms(FileSystem(backend=LocalFileSystem(root=str(tmp_path / "team")), namespace="a/b"))
    assert on_disk[:2] == ("a/b", "a/b:team")
    assert on_disk[2].startswith("a/b:team:") and str(tmp_path) not in on_disk[2]
    # A namespace resolved for a caller replaces the template.
    template = FileSystem(db, namespace="journals/{user_id}")
    assert _filesystem_id_forms(template, "journals/alice")[0] == "journals/alice"
    # On PostgreSQL the table is named with its schema, so one table name in two schemas is two stores.
    postgres = PostgresDb(id="pg-main", db_url="postgresql+psycopg://user:pass@localhost:1/none")
    in_archive = FileSystem(backend=DbFileSystem(db=postgres, db_schema="archive"), namespace="handbook")
    assert _filesystem_id_forms(FileSystem(postgres, namespace="handbook"))[2] == "handbook:pg-main:fs.agno_fs"
    assert _filesystem_id_forms(in_archive)[2] == "handbook:pg-main:archive.agno_fs"
    # Any other backend is named by its class.
    custom = SimpleNamespace(backend=_MemoryBackend(), namespace="handbook")
    assert _filesystem_id_forms(custom) == ("handbook", "handbook:_MemoryBackend")
    # The separator can never be part of a namespace, so no id reads as another namespace.
    assert _ID_SEPARATOR not in NAMESPACE_SAFE + "%{}"


def test_ids_are_the_shortest_form_that_names_one_store():
    from agno.os.routers.filesystem.utils import _filesystem_ids

    main = (("db", "main"), ("handbook", "handbook:main", "handbook:main:fs"))
    other = (("db", "other"), ("handbook", "handbook:other", "handbook:other:fs"))
    second_table = (("db", "main", "t2"), ("handbook", "handbook:main", "handbook:main:t2"))
    drafts = (("db", "main", "drafts"), ("drafts", "drafts:main", "drafts:main:fs"))

    assert _filesystem_ids([main, drafts]) == {main[0]: "handbook", drafts[0]: "drafts"}
    assert _filesystem_ids([main, other]) == {main[0]: "handbook:main", other[0]: "handbook:other"}
    assert _filesystem_ids([main, second_table]) == {main[0]: "handbook:main:fs", second_table[0]: "handbook:main:t2"}
    # A declared store keeps its id whatever agents hold; the other store takes the next free form.
    assert _filesystem_ids([main], [other]) == {main[0]: "handbook", other[0]: "handbook:other"}
    assert _filesystem_ids([main], [second_table]) == {main[0]: "handbook", second_table[0]: "handbook:main:t2"}
    assert _filesystem_ids([], [main, other]) == {main[0]: "handbook:main", other[0]: "handbook:other"}
    # The same store declared and held is one store.
    assert _filesystem_ids([main], [main]) == {main[0]: "handbook"}


def test_backends_with_the_same_names_are_numbered_in_order():
    from agno.os.routers.filesystem.utils import _filesystem_ids, _match_filesystem_id

    forms = ("handbook", "handbook:MemoryBackend")
    first, second, third = ("backend", 1), ("backend", 2), ("backend", 3)

    declared = _filesystem_ids([(first, forms), (second, forms)])
    assert declared == {first: "handbook:MemoryBackend", second: "handbook:MemoryBackend:2"}
    held = _filesystem_ids([(first, forms)], [(second, forms), (third, forms)])
    assert held == {first: "handbook", second: "handbook:MemoryBackend:2", third: "handbook:MemoryBackend:3"}
    # Its own id names one store even when another store shares the form.
    candidates = [(declared[first], forms), (declared[second], forms)]
    assert _match_filesystem_id("handbook:MemoryBackend", candidates) == [0]
    assert _match_filesystem_id("handbook:MemoryBackend:2", candidates) == [1]
    assert _match_filesystem_id("handbook", candidates) == [0, 1]


@pytest.mark.parametrize(
    "declared_stores, held_stores",
    [
        ([("main", "files"), ("main", "files"), ("main", "files:2")], []),
        ([], [("main", "files"), ("main", "files"), ("main", "files:2")]),
        ([("main", "files"), ("main", "files")], [("main", "files:2")]),
        ([("main:files", "t"), ("other", "t")], [("main", "files"), ("main", "files")]),
    ],
)
def test_a_numbered_id_never_names_another_store(tmp_path, declared_stores, held_stores, client_factory):
    from agno.fs.db import DbFileSystem

    stores = []
    for index, (db_id, table_name) in enumerate([*declared_stores, *held_stores]):
        database = SqliteDb(id=db_id, db_file=str(tmp_path / f"{index}.db"))
        store = FileSystem(DbFileSystem(db=database, table_name=table_name), namespace="notes")
        store.write(f"store-{index}.md", "x")
        stores.append(store)
    declared, held = stores[: len(declared_stores)], stores[len(declared_stores) :]
    agents = [Agent(id=f"agent-{index}", filesystem=store) for index, store in enumerate(held)]
    client = client_factory(*agents, filesystem=declared, authorization=False)

    ids = [entry["id"] for entry in client.get("/config").json()["filesystem"]["namespaces"]]
    assert len(set(ids)) == len(stores)
    opened = set()
    for filesystem_id in ids:
        response = client.get("/filesystem/entries", params={"filesystem_id": filesystem_id})
        assert response.status_code == 200, response.text
        opened.update(entry["path"] for entry in response.json()["entries"])
    assert opened == {f"store-{index}.md" for index in range(len(stores))}


def test_a_number_skips_forms_and_ids_already_used():
    from agno.os.routers.filesystem.utils import _filesystem_ids

    twin = ("notes", "notes:main", "notes:main:files")
    other = ("notes", "notes:main", "notes:main:files:2")

    assert _filesystem_ids([("a", twin), ("b", twin), ("c", other)]) == {
        "a": "notes:main:files",
        "b": "notes:main:files:3",
        "c": "notes:main:files:2",
    }
    # The ids of declared stores do not depend on what agents hold, so the held store moves.
    ids = _filesystem_ids([("a", twin), ("b", twin)], [("c", other)])
    assert ids == {"a": "notes:main:files", "b": "notes:main:files:2", "c": "notes:main:files:2:2"}


def test_ids_of_databases_with_the_same_names_do_not_depend_on_their_order(tmp_path, client_factory):
    from agno.fs.db import DbFileSystem

    stores = [
        FileSystem(DbFileSystem(db_url=f"sqlite:///{tmp_path}/{name}.db"), namespace="notes") for name in ("a", "b")
    ]
    opened = []
    for order in (stores, stores[::-1]):
        client = client_factory(filesystem=order, authorization=False)
        ids = [entry["id"] for entry in client.get("/config").json()["filesystem"]["namespaces"]]
        stores[0].write("a.md", "x")
        stores[1].write("b.md", "x")
        rows = {
            i: [e["path"] for e in client.get("/filesystem/entries", params={"filesystem_id": i}).json()["entries"]]
            for i in ids
        }
        assert sorted(rows.values()) == [["a.md"], ["b.md"]]
        opened.append(rows)
    assert opened[0] == opened[1]


def test_private_uri_memory_databases_are_two_filesystems(client_factory):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from agno.fs.db import DbFileSystem

    stores = []
    for name in ("a", "b"):
        engine = create_engine(
            "sqlite:///file::memory:?uri=true", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        store = FileSystem(DbFileSystem(db_engine=engine), namespace="notes")
        store.write(f"{name}.md", "x")
        stores.append(store)
    client = client_factory(filesystem=stores, authorization=False)

    assert len(client.get("/config").json()["filesystem"]["namespaces"]) == 2
    rows = client.get("/filesystem/files").json()["entries"]
    assert [row["path"] for row in rows] == ["a.md", "b.md"]


def test_the_backend_key_follows_the_port_the_schema_and_the_sqlite_uri(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from agno.fs.db import DbFileSystem
    from agno.os.routers.filesystem.utils import _database_place, _filesystem_backend_key

    monkeypatch.delenv("PGPORT", raising=False)

    def place(url: str) -> tuple:
        return _database_place(create_engine(url))

    assert place("postgresql+psycopg://db/app") == place("postgresql+psycopg://db:5432/app")
    assert place("postgresql+psycopg://db/app") != place("postgresql+psycopg://db:5433/app")
    assert place("postgresql+psycopg:///app?host=/run&port=5433") != place(
        "postgresql+psycopg:///app?host=/run&port=5434"
    )
    monkeypatch.setenv("PGPORT", "5433")
    assert place("postgresql+psycopg://db/app") == place("postgresql+psycopg://db:5433/app")
    # No host in the URL: the driver chooses the server, so engines are not compared.
    first, second = (create_engine("postgresql+psycopg:///app") for _ in range(2))
    assert _database_place(first) != _database_place(second)
    # A SQLite file is one file through a URI too.
    path = tmp_path / "one.db"
    assert place(f"sqlite:///file:{path}?uri=true") == place(f"sqlite:///{path}")
    assert place(f"sqlite:///file://{path}?uri=true") == place(f"sqlite:///{path}")

    def key(url: str, db_schema) -> tuple:
        backend = DbFileSystem(db_engine=create_engine(url), db_schema=db_schema)
        return _filesystem_backend_key(FileSystem(backend=backend, namespace="notes"))

    # Without a schema the search_path names the table; with one, the user does not matter.
    assert key("postgresql+psycopg://one@db/app", None) != key("postgresql+psycopg://two@db/app", None)
    assert key("postgresql+psycopg://one@db/app", "fs") == key("postgresql+psycopg://two@db/app", "fs")


@pytest.mark.parametrize("option", ["dbname", "host", "hostaddr", "port", "service"])
@pytest.mark.parametrize("through", ["query", "connect_args"])
def test_a_connection_override_names_another_database(option, through, client_factory):
    from sqlalchemy import create_engine

    from agno.fs.db import DbFileSystem

    url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
    engines = [
        create_engine(f"{url}?{option}={value}")
        if through == "query"
        else create_engine(url, connect_args={option: value})
        for value in ("1", "2")
    ]
    stores = [FileSystem(DbFileSystem(db_engine=engine), namespace="notes") for engine in engines]
    client = client_factory(filesystem=stores, authorization=False)

    ids = [entry["id"] for entry in client.get("/config").json()["filesystem"]["namespaces"]]
    assert len(set(ids)) == 2


def test_an_engine_whose_database_is_not_known_is_its_own_place():
    from sqlalchemy import create_engine, event
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.os.routers.filesystem.utils import _database_place

    url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
    base = _database_place(create_engine(url))
    # Options that do not choose the database, and the asynchronous driver, keep the place.
    assert base == ("postgresql", "localhost", "5432", "ai")
    assert _database_place(create_engine(url, connect_args={"application_name": "x"}, pool_size=1)) == base
    assert _database_place(create_async_engine(url).sync_engine) == base
    # An override that repeats the URL is the same database.
    assert _database_place(create_engine(f"{url}?dbname=ai")) == base

    listened = create_engine(url)
    event.listen(listened, "do_connect", lambda *args: None)
    for unknown in (create_engine(url, creator=lambda: None), listened, create_engine(f"{url}?dbname=host%3Dother")):
        assert _database_place(unknown) == ("engine", id(unknown))


@pytest.mark.parametrize("pgdatabase", [None, "postgres"])
def test_a_connection_that_names_no_database_is_not_merged_by_its_user(pgdatabase, client_factory, monkeypatch):
    from sqlalchemy import create_engine

    from agno.fs.db import DbFileSystem

    monkeypatch.delenv("PGDATABASE", raising=False)
    if pgdatabase is not None:
        monkeypatch.setenv("PGDATABASE", pgdatabase)
    urls = ("postgresql+psycopg://ai:ai@localhost:5432", "postgresql+psycopg://ai:ai@localhost:5432/ai")
    stores = [FileSystem(DbFileSystem(db_engine=create_engine(url)), namespace="notes") for url in urls]
    client = client_factory(filesystem=stores, authorization=False)

    ids = [entry["id"] for entry in client.get("/config").json()["filesystem"]["namespaces"]]
    assert len(set(ids)) == 2


@pytest.mark.parametrize("variable", ["PGSERVICE", "PGHOSTADDR"])
def test_an_environment_that_redirects_connections_leaves_the_place_unknown(variable, monkeypatch):
    from sqlalchemy import create_engine

    from agno.os.routers.filesystem.utils import _database_place

    monkeypatch.setenv(variable, "elsewhere")
    engine = create_engine("postgresql+psycopg://ai:ai@localhost:5432/ai")
    assert _database_place(engine) == ("engine", id(engine))


def test_a_sqlite_name_is_a_uri_only_when_opened_as_one(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from agno.os.routers.filesystem.utils import _database_place

    monkeypatch.chdir(tmp_path)
    as_uri = _database_place(create_engine("sqlite:///file:one.db?uri=true"))
    assert as_uri == _database_place(create_engine("sqlite:///one.db"))
    assert as_uri != _database_place(create_engine("sqlite:///file:one.db"))


def test_a_failing_agent_does_not_hide_a_declared_filesystem(db, client_factory):
    handbook = FileSystem(db, namespace="handbook")
    handbook.write("style.md", "x\n")
    client = client_factory(_failing_factory(db), db=db, filesystem=handbook)

    for path, params in (
        ("entries", {"namespace": "handbook"}),
        ("files", {"namespace": "handbook"}),
        ("files", {}),
    ):
        response = client.get(f"/filesystem/{path}", params=params, headers=_headers("alice"))
        assert response.status_code == 200, response.text
        assert [row["path"] for row in response.json()["entries"]] == ["style.md"]
    # A name no declared filesystem has may be the failing agent's, so its failure is reported.
    for params in ({"namespace": "other"}, {"filesystem_id": "other"}):
        assert client.get("/filesystem/entries", params=params, headers=_headers("alice")).status_code == 500


def test_a_filesystem_on_an_async_database_is_browsable_on_every_route(tmp_path, client_factory):
    import asyncio

    from agno.db.sqlite import AsyncSqliteDb

    async_db = AsyncSqliteDb(id="async-db", db_file=str(tmp_path / "async.db"))
    declared = FileSystem(async_db, namespace="handbook")
    held = FileSystem(async_db, namespace="held")

    async def seed() -> None:
        await declared.awrite("guides/style.md", "declared needle\n")
        await held.awrite("guides/style.md", "held needle\n")

    asyncio.run(seed())
    client = client_factory(Agent(id="keeper", db=async_db, filesystem=held), db=async_db, filesystem=declared)

    for filesystem_id, expected in (("handbook", "declared needle\n"), ("held", "held needle\n")):
        by_id = {"filesystem_id": filesystem_id}
        listed = client.get("/filesystem/entries", params=by_id, headers=_headers("alice"))
        assert listed.status_code == 200, filesystem_id
        assert [(entry["path"], entry["type"]) for entry in listed.json()["entries"]] == [("guides", "directory")]
        nested = client.get("/filesystem/entries", params={**by_id, "directory": "guides"}, headers=_headers("alice"))
        assert [(entry["path"], entry["type"]) for entry in nested.json()["entries"]] == [("guides/style.md", "file")]
        content = client.get(
            "/filesystem/content", params={**by_id, "path": "guides/style.md"}, headers=_headers("alice")
        )
        assert content.json()["content"] == expected
        search = client.get("/filesystem/search", params={**by_id, "query": "needle"}, headers=_headers("alice"))
        assert [entry["path"] for entry in search.json()["entries"]] == ["guides/style.md"]
        rows = client.get("/filesystem/files", params=by_id, headers=_headers("alice"))
        assert [row["path"] for row in rows.json()["entries"]] == ["guides/style.md"]


# --- One FileSystem declared on two AgentOS instances ---


def _serve(db, filesystem, user_isolation: bool) -> TestClient:
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        filesystem=filesystem,
        authorization=Authorization(verification_keys=[JWT_SECRET], algorithm="HS256"),
        user_isolation=user_isolation,
    )
    return TestClient(agent_os.get_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("isolated_first", [True, False])
def test_one_filesystem_declared_on_two_agentos_follows_the_isolation_setting_of_each(db, isolated_first):
    handbook = FileSystem(db, namespace="handbook")
    chose_shared = FileSystem(db, namespace="shared", user_scoped=False)
    chose_partitions = FileSystem(db, namespace="private", user_scoped=True)
    declared = [handbook, chose_shared, chose_partitions]
    if isolated_first:
        isolated, open_to_all = _serve(db, declared, True), _serve(db, declared, False)
    else:
        open_to_all, isolated = _serve(db, declared, False), _serve(db, declared, True)

    # The objects are the caller's: neither AgentOS wrote its setting onto them.
    assert (handbook.user_scoped, chose_shared.user_scoped, chose_partitions.user_scoped) == (None, False, True)

    def isolation(client: TestClient) -> dict:
        entries = _config_entries(client, _headers("alice", ["config:read"]))
        return {entry["id"]: entry["user_isolation"] for entry in entries}

    # Left unset, a store follows each AgentOS. A store that chose keeps its choice on both.
    assert isolation(isolated) == {"handbook": True, "shared": False, "private": True}
    assert isolation(open_to_all) == {"handbook": False, "shared": False, "private": True}

    handbook.write("a.md", "everyone's\n")
    handbook.resolve(user_id="alice").write("a.md", "alice's\n")
    by_id = {"filesystem_id": "handbook", "path": "a.md"}
    for client, content, owner in ((isolated, "alice's\n", "alice"), (open_to_all, "everyone's\n", None)):
        read = client.get("/filesystem/content", params=by_id, headers=_headers("alice", FILES_ONLY))
        assert read.status_code == 200
        assert (read.json()["content"], read.json()["user_id"]) == (content, owner)
    isolated.close()
    open_to_all.close()


# --- Ids are the same with and without an agent filter ---


def test_an_id_from_an_agent_filtered_listing_opens_that_filesystem_on_its_own(tmp_path, db, client_factory):
    from agno.fs.local import LocalFileSystem

    in_db = FileSystem(db, namespace="notes")
    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "files")), namespace="notes")
    client = client_factory(
        Agent(id="db-agent", db=db, filesystem=in_db), Agent(id="disk-agent", db=db, filesystem=on_disk)
    )
    in_db.write("a.md", "db\n")
    on_disk.write("b.md", "disk\n")
    ids = {"db-agent": ("notes:filesystem-db", "a.md"), "disk-agent": ("notes:files", "b.md")}

    for agent_id, (filesystem_id, path) in ids.items():
        by_agent = {"agent_id": agent_id}
        rows = client.get("/filesystem/files", params=by_agent, headers=_headers("alice")).json()["entries"]
        assert [(row["filesystem_id"], row["path"]) for row in rows] == [(filesystem_id, path)]
        for route, params in ONE_FILESYSTEM_ROUTES:
            listed = client.get(route, params={**params, **by_agent, "path": path}, headers=_headers("alice"))
            assert listed.status_code == 200, route
            assert listed.json()["filesystem_id"] == filesystem_id, route
            # The id an agent-filtered response carries opens the same filesystem with no agent named.
            alone = client.get(
                route, params={**params, "filesystem_id": filesystem_id, "path": path}, headers=_headers("alice")
            )
            assert alone.status_code == 200, route
            assert alone.json()["filesystem_id"] == filesystem_id, route
            # The namespace names both stores. With the agent that holds one, it is that one, under its id.
            shared_form = client.get(
                route, params={**params, **by_agent, "filesystem_id": "notes", "path": path}, headers=_headers("alice")
            )
            assert shared_form.status_code == 200, route
            assert shared_form.json()["filesystem_id"] == filesystem_id, route
            assert (
                client.get(route, params={**params, "filesystem_id": "notes"}, headers=_headers("alice")).status_code
                == 409
            )


def test_a_filesystem_id_and_an_agent_id_must_name_the_same_filesystem(tmp_path, db, archive_db, client_factory):
    declared = FileSystem(db, namespace="handbook")
    elsewhere = FileSystem(archive_db, namespace="handbook")
    declared.write("style.md", "declared\n")
    elsewhere.write("style.md", "the archivist's own\n")

    def content(client, **params) -> tuple:
        response = client.get("/filesystem/content", params={"path": "style.md", **params}, headers=_headers("alice"))
        return response.status_code, response.json().get("content")

    # No agent holds the declared store. Its id names it and nothing else, whatever agent is named with it.
    client = client_factory(Agent(id="archivist", db=db, filesystem=elsewhere), db=db, filesystem=declared)
    assert content(client, filesystem_id="handbook") == (200, "declared\n")
    assert content(client, filesystem_id="handbook", agent_id="archivist") == (404, None)
    assert content(client, filesystem_id="handbook:filesystem-db", agent_id="archivist") == (404, None)
    assert content(client, filesystem_id="handbook:archive-db", agent_id="archivist") == (200, "the archivist's own\n")
    assert content(client, agent_id="archivist") == (200, "the archivist's own\n")
    rows = client.get(
        "/filesystem/files", params={"filesystem_id": "handbook", "agent_id": "archivist"}, headers=_headers("alice")
    )
    assert rows.status_code == 200 and rows.json()["entries"] == []

    # An agent that holds the declared store is named with it.
    client = client_factory(
        Agent(id="archivist", db=db, filesystem=elsewhere),
        Agent(id="reader", db=db, filesystem=FileSystem(db, namespace="handbook")),
        db=db,
        filesystem=declared,
    )
    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert {entry["id"]: [agent["id"] for agent in entry["agents"]] for entry in entries} == {
        "handbook": ["reader"],
        "handbook:archive-db": ["archivist"],
    }
    assert content(client, filesystem_id="handbook", agent_id="archivist") == (404, None)
    assert content(client, filesystem_id="handbook", agent_id="reader") == (200, "declared\n")
    assert content(client, filesystem_id="handbook:archive-db", agent_id="reader") == (404, None)


def test_an_agent_alone_still_selects_its_own_first_filesystem(db, client_factory):
    first, second = FileSystem(db, namespace="zeta"), FileSystem(db, namespace="alpha")
    client = client_factory(
        # An agent listed earlier holds the second store, and a declaration names it too.
        Agent(id="a-early", db=db, filesystem=FileSystem(db, namespace="alpha")),
        Agent(id="writer", db=db, tools=[first.tools(name="own_files"), second.tools(read_only=True)]),
        db=db,
        filesystem=FileSystem(db, namespace="alpha"),
    )
    first.write("mine.md", "first\n")

    listed = client.get("/filesystem/entries", params={"agent_id": "writer"}, headers=_headers("alice"))
    assert listed.status_code == 200
    assert (listed.json()["filesystem_id"], listed.json()["agent_ids"]) == ("zeta", ["writer"])
    assert [entry["path"] for entry in listed.json()["entries"]] == ["mine.md"]


def test_a_request_that_names_an_agent_reads_the_store_as_that_agent_holds_it(db, client_factory):
    declared = FileSystem(db, namespace="handbook")
    smaller = FileSystem(db, namespace="handbook", max_namespace_bytes=5_000_000)
    client = client_factory(
        Agent(id="abe", db=db, filesystem=FileSystem(db, namespace="handbook")),
        Agent(id="writer", db=db, filesystem=smaller),
        db=db,
        filesystem=declared,
    )

    def listed(**params) -> tuple:
        body = client.get("/filesystem/entries", params=params, headers=_headers("alice")).json()
        return body["filesystem_id"], body["agent_ids"], body["usage"]["bytes_limit"]

    # Read by its id alone, the declared store loads no agent.
    assert listed(filesystem_id="handbook") == ("handbook", [], 20_000_000)
    # With an agent named it is the same store under the same id, with the limit of that agent.
    assert listed(agent_id="writer") == ("handbook", ["abe", "writer"], 5_000_000)
    assert listed(agent_id="writer", filesystem_id="handbook") == ("handbook", ["abe", "writer"], 5_000_000)
    assert listed(agent_id="abe") == ("handbook", ["abe", "writer"], 20_000_000)


def test_another_agent_that_cannot_be_built_does_not_fail_a_request_that_names_an_agent(
    db, client_factory, monkeypatch
):
    from agno.os.routers.filesystem import router as filesystem_router

    own = FileSystem(db, namespace="own")
    own.write("mine.md", "mine\n")
    client = client_factory(_failing_factory(db), Agent(id="writer", db=db, filesystem=own), db=db)
    resolved: list[str] = []
    resolve_agent = filesystem_router.resolve_agent

    async def spy(agent_id, *args, **kwargs):
        resolved.append(agent_id)
        return await resolve_agent(agent_id, *args, **kwargs)

    monkeypatch.setattr(filesystem_router, "resolve_agent", spy)

    # A listing of every agent's files reads the broken agent and fails.
    assert client.get("/filesystem/files", headers=_headers("alice")).status_code == 500
    # A request for one agent reads the others only to settle the ids.
    rows = client.get("/filesystem/files", params={"agent_id": "writer"}, headers=_headers("alice"))
    assert rows.status_code == 200
    assert [(row["filesystem_id"], row["path"]) for row in rows.json()["entries"]] == [("own", "mine.md")]
    resolved.clear()
    listed = client.get("/filesystem/entries", params={"agent_id": "writer"}, headers=_headers("alice"))
    assert listed.status_code == 200 and listed.json()["filesystem_id"] == "own"
    # Each agent is loaded once, the named one included.
    assert sorted(resolved) == ["broken", "writer"]
    # The named agent's own failure is the request's.
    assert (
        client.get("/filesystem/entries", params={"agent_id": "broken"}, headers=_headers("alice")).status_code == 500
    )


def test_a_shared_declaration_and_a_user_scoped_view_of_one_store_are_one_entry(db, client_factory):
    declared = FileSystem(db, namespace="handbook", user_scoped=False)
    held = FileSystem(db, namespace="handbook", user_scoped=True)
    client = client_factory(Agent(id="writer", db=db, filesystem=held), db=db, filesystem=declared)
    declared.write("shared.md", "shared\n")
    held.resolve(user_id="alice").write("alice.md", "alice's\n")
    held.resolve(user_id="bob").write("bob.md", "bob's\n")
    alice, admin = _headers("alice", ["agents:read", "filesystem:read", "config:read"]), _admin_headers()

    # One entry, described by the declaration.
    assert _config_entries(client, alice) == [_declared_entry("handbook", agents=[{"id": "writer"}])]

    def listed(headers: dict, **params) -> list:
        entries = client.get("/filesystem/entries", params=params, headers=headers).json()["entries"]
        return [(entry["path"], entry["user_id"]) for entry in entries]

    # By its id the store is the shared partition, for a user and for an admin.
    for headers in (alice, admin):
        assert listed(headers, filesystem_id="handbook") == [("shared.md", None)]
        rows = client.get("/filesystem/files", headers=headers).json()["entries"]
        assert [(row["path"], row["user_id"]) for row in rows] == [("shared.md", None)]
    # With the agent named it is read as the agent holds it: a user's own files, and every partition for an admin.
    assert listed(alice, agent_id="writer") == [("alice.md", "alice")]
    assert listed(admin, agent_id="writer") == [("alice.md", "alice"), ("bob.md", "bob"), ("shared.md", None)]


# --- Reading one file as an admin ---


def test_an_admin_reads_a_file_of_a_partitioned_store_on_an_async_database(tmp_path, client_factory):
    import asyncio

    from agno.db.sqlite import AsyncSqliteDb

    async_db = AsyncSqliteDb(id="async-db", db_file=str(tmp_path / "async.db"))
    handbook = FileSystem(async_db, namespace="handbook", user_scoped=True)

    async def seed() -> None:
        await handbook.partition(None).awrite("style.md", "shared\n")
        await handbook.resolve(user_id="alice").awrite("style.md", "alice's\n")

    asyncio.run(seed())
    client = client_factory(db=async_db, filesystem=handbook, user_isolation=True)
    admin = _admin_headers()
    by_id = {"filesystem_id": "handbook", "path": "style.md"}

    # With no user named an admin reads the shared partition.
    shared = client.get("/filesystem/content", params=by_id, headers=admin)
    assert shared.status_code == 200, shared.text
    assert (shared.json()["content"], shared.json()["user_id"]) == ("shared\n", None)
    named = client.get("/filesystem/content", params={**by_id, "user_id": "alice"}, headers=admin)
    assert (named.json()["content"], named.json()["user_id"]) == ("alice's\n", "alice")


def test_reading_one_file_does_not_list_the_users_of_the_store(db, client_factory, monkeypatch):
    handbook = FileSystem(db, namespace="handbook", user_scoped=True)
    handbook.partition(None).write("style.md", "shared\n")
    handbook.resolve(user_id="alice").write("style.md", "alice's\n")
    client = client_factory(db=db, filesystem=handbook, user_isolation=True)

    def refuse(self):
        raise AssertionError("one file is read from one partition: the users are not listed")

    monkeypatch.setattr(FileSystem, "partitions", refuse)
    monkeypatch.setattr(FileSystem, "apartitions", refuse)
    read = client.get(
        "/filesystem/content", params={"filesystem_id": "handbook", "path": "style.md"}, headers=_admin_headers()
    )
    assert read.status_code == 200, read.text
    assert (read.json()["content"], read.json()["user_id"]) == ("shared\n", None)


# --- One table reached through two wrappers ---


@pytest.mark.parametrize("held_through", ["engine", "database"])
def test_two_wrappers_on_one_engine_table_and_namespace_are_one_filesystem(tmp_path, db, held_through, client_factory):
    from agno.fs.db import DbFileSystem

    declared = FileSystem(backend=DbFileSystem(db_engine=db.db_engine), namespace="handbook")
    if held_through == "engine":
        held = FileSystem(backend=DbFileSystem(db_engine=db.db_engine), namespace="handbook")
    else:
        held = FileSystem(db, namespace="handbook")
    other_table = FileSystem(backend=DbFileSystem(db_engine=db.db_engine, table_name="other_fs"), namespace="handbook")
    client = client_factory(Agent(id="writer", db=db, filesystem=held), db=db, filesystem=[declared, other_table])
    declared.write("style.md", "one store\n")

    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert [
        (entry["table_name"], entry["declared"], [agent["id"] for agent in entry["agents"]]) for entry in entries
    ] == [
        ("agno_fs", True, ["writer"]),
        ("other_fs", True, []),
    ]
    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["path"], row["agent_ids"]) for row in rows] == [("style.md", ["writer"])]


def test_the_backend_key_names_the_database_and_table_not_the_wrapper(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from agno.db.sqlite import AsyncSqliteDb
    from agno.fs.db import DbFileSystem
    from agno.os.routers.filesystem.utils import _database_place, _filesystem_backend_key

    path = tmp_path / "one.db"
    one, same = create_engine(f"sqlite:///{path}"), create_engine(f"sqlite:///{path}")
    other = create_engine(f"sqlite:///{tmp_path / 'other.db'}")

    def key(backend) -> tuple:
        return _filesystem_backend_key(FileSystem(backend=backend, namespace="handbook"))

    base = key(DbFileSystem(db_engine=one))
    # Another wrapper, another engine, a database object and an asynchronous one: all one table.
    assert key(DbFileSystem(db_engine=one)) == base
    assert key(DbFileSystem(db_engine=same)) == base
    assert key(DbFileSystem(db=SqliteDb(id="named", db_file=str(path)))) == base
    assert _filesystem_backend_key(FileSystem(AsyncSqliteDb(db_file=str(path)), namespace="handbook")) == base
    # Another table or another database is another store.
    assert key(DbFileSystem(db_engine=one, table_name="other_fs")) != base
    assert key(DbFileSystem(db_engine=other)) != base
    # Each in-memory database is its own.
    memory = [create_engine("sqlite://"), create_engine("sqlite://")]
    assert key(DbFileSystem(db_engine=memory[0])) == key(DbFileSystem(db_engine=memory[0]))
    assert key(DbFileSystem(db_engine=memory[0])) != key(DbFileSystem(db_engine=memory[1]))
    # A path is the same file however it is written.
    monkeypatch.chdir(tmp_path)
    relative = create_engine("sqlite:///one.db")
    assert key(DbFileSystem(db_engine=relative)) == base
    for engine in (one, same, other, relative, *memory):
        engine.dispose()

    def place(url: str) -> tuple:
        return _database_place(create_engine(url))

    # A PostgreSQL database is the same through either driver and for any user, and another on another server.
    assert place("postgresql+psycopg://ai:ai@db.internal:5432/app") == place(
        "postgresql+psycopg_async://reader@db.internal:5432/app"
    )
    assert place("postgresql+psycopg://ai@db.internal:5432/app") != place(
        "postgresql+psycopg://ai@db.internal:5432/other"
    )
    assert place("postgresql+psycopg://ai@db.internal:5432/app") != place(
        "postgresql+psycopg://ai@replica.internal:5432/app"
    )
    assert place("postgresql+psycopg://ai@/app?host=/var/run/one") != place(
        "postgresql+psycopg://ai@/app?host=/var/run/two"
    )


# --- A namespace that names a team ---


def test_a_team_namespace_held_by_an_agent_is_listed_as_written_and_cannot_be_opened(db, client_factory):
    template = FileSystem(db, namespace="teams/{team_id}/notes")
    client = client_factory(Agent(id="writer", db=db, filesystem=template), db=db, filesystem=template)

    # An agent fills {agent_id} only. /config lists the namespace as it is written.
    entries = _config_entries(client, _headers("alice", ["config:read", "agents:read"]))
    assert [(entry["id"], entry["namespace"], entry["declared"], entry["agents"]) for entry in entries] == [
        ("teams/{team_id}/notes", "teams/{team_id}/notes", False, [{"id": "writer"}])
    ]
    # No request fills {team_id}, so the routes do not open it.
    by_id = client.get(
        "/filesystem/entries", params={"filesystem_id": "teams/{team_id}/notes"}, headers=_headers("alice")
    )
    assert by_id.status_code == 404
    by_agent = client.get("/filesystem/entries", params={"agent_id": "writer"}, headers=_headers("alice"))
    assert by_agent.status_code == 400 and "team_id" in by_agent.json()["detail"]
    assert client.get("/filesystem/files", headers=_headers("alice")).json()["entries"] == []
