from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent, RemoteAgent
from agno.agent.factory import AgentFactory
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
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

        def create(*agents, user_isolation: bool = False, db=None, registry=None) -> TestClient:
            agent_os = AgentOS(
                id=OS_ID,
                agents=list(agents),
                db=db,
                registry=registry,
                authorization=True,
                authorization_config=AuthorizationConfig(
                    verification_keys=[JWT_SECRET],
                    algorithm="HS256",
                    user_isolation=user_isolation,
                ),
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


def test_global_files_skips_remote_agents_but_explicit_requests_fail(db, client_factory):
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


def test_read_only_toolkit_setting_is_reported_read_only(db, client_factory):
    agent = Agent(id="answerer", db=db, filesystem=FileSystem(db, namespace="research").tools(read_only=True))
    client = client_factory(agent)

    config = client.get("/config", headers=_headers("alice", ["config:read", "agents:read"])).json()
    instance = config["filesystem"]["namespaces"][0]
    assert instance["agents"] == [{"id": "answerer", "access": "read_only"}]
    assert "read_only_agents" not in instance


@pytest.mark.parametrize("read_only_first", [True, False])
def test_config_full_access_takes_precedence_on_shared_store(db, read_only_first, client_factory):
    shared = FileSystem(db, namespace="shared")
    reader = shared.tools(read_only=True)
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
    answerer = Agent(id="answerer", db=db, filesystem=shared.tools(read_only=True))
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
    client = client_factory(Agent(id="reader", db=db, filesystem=handbook.tools(read_only=True)), user_isolation=True)
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
