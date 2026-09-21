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
            "scopes": scopes if scopes is not None else ["agents:read"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _scoped_headers(user_id: str, scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, scopes)}"}


def _client(*agents, user_isolation: bool = False) -> TestClient:
    os = AgentOS(
        id=OS_ID,
        agents=list(agents),
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=user_isolation,
        ),
    )
    return TestClient(os.get_app(), raise_server_exceptions=False)


def test_list_read_and_search_run_behind_auth_middleware(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="notes", db=db, filesystem=True)
    client = _client(agent)
    agent.filesystem_instance.write("notes/state.md", "alpha needle\nbeta\n")  # type: ignore[union-attr]

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


def test_global_files_lists_and_searches_configured_agent_filesystems(tmp_path):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agents.db"))
    notes = Agent(id="notes", db=db, filesystem=True)
    reports = Agent(id="reports", db=db, filesystem=True)
    client = _client(notes, reports)
    notes.filesystem_instance.write("notes/state.md", "alpha needle")  # type: ignore[union-attr]
    reports.filesystem_instance.write("reports/summary.md", "beta")  # type: ignore[union-attr]

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


def test_global_files_merges_agents_sharing_the_same_filesystem(tmp_path, monkeypatch):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(db, namespace="shared")
    filesystem.write("state.md", "shared")
    client = _client(
        Agent(id="one", db=db, filesystem=filesystem),
        Agent(id="two", db=db, filesystem=filesystem),
    )
    list_files = AsyncMock(wraps=filesystem.alist)
    search_files = AsyncMock(wraps=filesystem.asearch)
    monkeypatch.setattr(filesystem, "alist", list_files)
    monkeypatch.setattr(filesystem, "asearch", search_files)

    response = client.get("/filesystem/files", headers=_headers("alice"))
    list_files.assert_awaited_once()
    searched = client.get("/filesystem/files", params={"query": "shared"}, headers=_headers("alice"))
    assert list_files.await_count == 2
    search_files.assert_awaited_once()
    assert searched.status_code == 200
    assert searched.json()["entries"][0]["agent_ids"] == ["one", "two"]
    config = client.get("/config", headers=_scoped_headers("alice", ["config:read"]))

    assert response.status_code == 200
    assert response.json()["entries"] == [
        {
            "namespace": "shared",
            "path": "state.md",
            "agent_ids": ["one", "two"],
            "size_bytes": 6,
            "version": 1,
            "updated_at": response.json()["entries"][0]["updated_at"],
            "snippet": None,
            "line": None,
            "match_count": None,
        }
    ]
    assert config.status_code == 200
    assert config.json()["filesystem"]["instances"][0]["agents"] == ["one", "two"]

    restricted = client.get("/filesystem/files", headers=_scoped_headers("alice", ["agents:one:read"]))
    assert restricted.status_code == 200
    assert restricted.json()["entries"][0]["agent_ids"] == ["one"]


def test_global_files_skips_remote_agents_but_explicit_requests_fail(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(db, namespace="notes")
    filesystem.write("state.md", "local")
    agent = Agent(id="notes", db=db, filesystem=filesystem)
    remote = RemoteAgent(base_url="http://localhost:9999", agent_id="remote")
    client = _client(agent, remote)

    listed = client.get("/filesystem/files", headers=_headers("alice"))
    explicit = client.get("/filesystem/files", params={"agent_id": "remote"}, headers=_headers("alice"))

    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["state.md"]
    assert explicit.status_code == 501


def test_global_files_rejects_empty_scopes(tmp_path):
    agent = Agent(id="notes", db=SqliteDb(db_file=str(tmp_path / "agents.db")), filesystem=True)
    client = _client(agent)

    response = client.get("/filesystem/files", headers=_scoped_headers("alice", []))

    assert response.status_code == 403


@pytest.mark.parametrize("namespace", [None, "My Namespace", "Tenants/{user_id}/{agent_id}"])
def test_config_namespace_filters_global_files_for_the_caller(tmp_path, namespace):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    configured_filesystem = FileSystem(db, namespace=namespace) if namespace else True
    agent = Agent(id="notes", db=db, filesystem=configured_filesystem)
    client = _client(agent, user_isolation=True)
    filesystem = agent.filesystem_instance
    assert filesystem is not None
    filesystem.resolve(user_id="Alice", agent_id="notes").write("state.md", "private")

    config = client.get("/config", headers=_scoped_headers("Alice", ["config:read"]))
    assert config.status_code == 200
    resolved_namespace = config.json()["filesystem"]["instances"][0]["namespace"]
    listed = client.get("/filesystem/files", params={"namespace": resolved_namespace}, headers=_headers("Alice"))

    assert listed.status_code == 200
    assert [(entry["namespace"], entry["path"]) for entry in listed.json()["entries"]] == [
        (resolved_namespace, "state.md")
    ]
    if namespace != "My Namespace":
        other_user = client.get(
            "/filesystem/files", params={"namespace": resolved_namespace}, headers=_headers("alice")
        )
        assert other_user.status_code == 200
        assert other_user.json()["entries"] == []


def test_global_files_only_lists_agents_visible_to_the_caller(tmp_path):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agents.db"))
    notes = Agent(id="notes", db=db, filesystem=True)
    reports = Agent(id="reports", db=db, filesystem=True)
    client = _client(notes, reports)
    notes.filesystem_instance.write("notes.md", "notes")  # type: ignore[union-attr]
    reports.filesystem_instance.write("reports.md", "reports")  # type: ignore[union-attr]

    response = client.get(
        "/filesystem/files",
        headers=_scoped_headers("alice", ["agents:notes:read"]),
    )

    assert response.status_code == 200
    assert [entry["agent_ids"] for entry in response.json()["entries"]] == [["notes"]]


def test_managed_isolation_requires_authentication_and_separates_users(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="notes", db=db, filesystem=True)
    client = _client(agent, user_isolation=True)
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


def test_explicit_template_binds_user_and_agent_from_trusted_context(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    filesystem = FileSystem(db, namespace="Tenants/{user_id}/Agents/{agent_id}")
    agent = Agent(id="notes", db=db, filesystem=filesystem)
    client = _client(agent, user_isolation=True)
    filesystem.resolve(user_id="Alice", agent_id="notes").write("state.md", "private")

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "notes", "path": "state.md"},
        headers=_headers("Alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "private"


def test_unresolved_explicit_template_returns_400(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    agent = Agent(
        id="notes",
        db=db,
        filesystem=FileSystem(db, namespace="teams/{team_id}/agents/{agent_id}"),
    )
    client = _client(agent)

    response = client.get("/filesystem/entries", params={"agent_id": "notes"}, headers=_headers("alice"))

    assert response.status_code == 400
    assert "team_id" in response.text


def test_factory_agent_filesystem_is_browsable(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    filesystem = FileSystem(db, namespace="factories/{agent_id}")
    filesystem.resolve(agent_id="factory-notes").write("state.md", "factory")
    factory = AgentFactory(
        id="factory-notes",
        db=db,
        factory=lambda ctx: Agent(id="factory-notes", db=db, filesystem=filesystem),
    )
    client = _client(factory)

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "factory-notes", "path": "state.md"},
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "factory"


def test_stored_agent_route_preserves_encoded_namespace_and_separate_db(tmp_path):
    catalog_db = SqliteDb(id="catalog-db", db_file=str(tmp_path / "catalog.db"))
    files_db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    filesystem = FileSystem(files_db, namespace="My Namespace")
    filesystem.write("state.md", "separate")
    Agent(id="stored-notes", db=catalog_db, filesystem=filesystem).save()
    os = AgentOS(
        id=OS_ID,
        agents=[],
        db=catalog_db,
        registry=Registry(dbs=[files_db]),
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
        ),
    )
    client = TestClient(os.get_app(), raise_server_exceptions=False)

    response = client.get(
        "/filesystem/content",
        params={"agent_id": "stored-notes", "path": "state.md"},
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["content"] == "separate"


def test_content_preview_has_a_continuation_offset(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="notes", db=db, filesystem=True)
    client = _client(agent)
    agent.filesystem_instance.write("large.md", "abcdefghij")  # type: ignore[union-attr]

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


def test_config_describes_filesystem_at_os_level(tmp_path):
    db = SqliteDb(id="filesystem-db", db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="notes", db=db, filesystem=True)
    factory = AgentFactory(
        id="factory-notes",
        db=db,
        factory=lambda ctx: Agent(id="factory-notes", db=db, filesystem=True),
    )
    client = _client(agent, factory, user_isolation=True)

    response = client.get("/config", headers=_scoped_headers("alice", ["config:read"]))

    assert response.status_code == 200
    agents = {entry["id"]: entry for entry in response.json()["agents"]}
    assert response.json()["filesystem"] == {
        "instances": [
            {
                "backend_type": "db",
                "db_id": "filesystem-db",
                "table_name": "agno_fs",
                "namespace": "users/alice/notes",
                "user_isolation": True,
                "max_file_bytes": 1_000_000,
                "max_namespace_bytes": 20_000_000,
                "agents": ["notes"],
                "read_only_agents": [],
            }
        ]
    }
    assert "filesystem" not in agents["notes"]
    assert "filesystem" not in agents["factory-notes"]


def test_manual_read_only_toolkit_is_discovered_and_browsable(tmp_path):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agent.db"))
    shared = FileSystem(db, namespace="research/decisions")
    recorder = Agent(id="recorder", db=db, filesystem=shared)
    answerer = Agent(id="answerer", db=db, tools=[FileSystem(db, namespace="research/decisions").tools(read_only=True)])
    client = _client(recorder, answerer)
    shared.write("decisions.md", "vector db: pgvector\n")

    config = client.get("/config", headers=_scoped_headers("alice", ["config:read"])).json()
    assert [(i["namespace"], i["agents"], i["read_only_agents"]) for i in config["filesystem"]["instances"]] == [
        ("research/decisions", ["answerer", "recorder"], ["answerer"])
    ]
    agents = client.get("/agents", headers=_headers("alice")).json()
    assert {entry["id"]: entry["filesystem"] for entry in agents} == {"recorder": True, "answerer": True}

    listed = client.get("/filesystem/entries", params={"agent_id": "answerer"}, headers=_headers("alice"))
    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["decisions.md"]

    rows = client.get("/filesystem/files", headers=_headers("alice")).json()["entries"]
    assert [(row["path"], row["agent_ids"]) for row in rows] == [("decisions.md", ["answerer", "recorder"])]


def test_read_only_toolkit_setting_is_reported_read_only(tmp_path):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="answerer", db=db, filesystem=FileSystem(db, namespace="research").tools(read_only=True))
    client = _client(agent)

    config = client.get("/config", headers=_scoped_headers("alice", ["config:read"])).json()
    assert config["filesystem"]["instances"][0]["read_only_agents"] == ["answerer"]


def test_namespace_selects_among_an_agents_filesystems(tmp_path):
    db = SqliteDb(id="multi-db", db_file=str(tmp_path / "agent.db"))
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
    client = _client(agent)
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


def test_namespace_alone_addresses_a_filesystem_within_caller_access(tmp_path):
    db = SqliteDb(id="shared-db", db_file=str(tmp_path / "agent.db"))
    shared = FileSystem(db, namespace="research/decisions")
    private = FileSystem(db, namespace="private")
    recorder = Agent(id="recorder", db=db, filesystem=shared)
    answerer = Agent(id="answerer", db=db, filesystem=shared.tools(read_only=True))
    keeper = Agent(id="keeper", db=db, filesystem=private)
    client = _client(recorder, answerer, keeper)
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
    scoped = _scoped_headers("alice", ["agents:recorder:read"])
    allowed = client.get(
        "/filesystem/content", params={"namespace": "research/decisions", "path": "decisions.md"}, headers=scoped
    )
    assert allowed.status_code == 200
    assert allowed.json()["agent_ids"] == ["recorder"]
    hidden = client.get("/filesystem/content", params={"namespace": "private", "path": "secret.md"}, headers=scoped)
    assert hidden.status_code == 404
    forbidden = client.get("/filesystem/entries", params={"agent_id": "keeper"}, headers=scoped)
    assert forbidden.status_code == 403


def test_same_namespace_on_two_backends_needs_an_agent(tmp_path):
    from agno.fs.local import LocalFileSystem

    db = SqliteDb(id="one-db", db_file=str(tmp_path / "agent.db"))
    in_db = FileSystem(db, namespace="notes")
    on_disk = FileSystem(backend=LocalFileSystem(root=str(tmp_path / "files")), namespace="notes")
    client = _client(Agent(id="db-agent", db=db, filesystem=in_db), Agent(id="disk-agent", db=db, filesystem=on_disk))
    in_db.write("a.md", "db\n")
    on_disk.write("b.md", "disk\n")

    ambiguous = client.get("/filesystem/entries", params={"namespace": "notes"}, headers=_headers("alice"))
    assert ambiguous.status_code == 409

    chosen = client.get(
        "/filesystem/entries", params={"namespace": "notes", "agent_id": "disk-agent"}, headers=_headers("alice")
    )
    assert [entry["path"] for entry in chosen.json()["entries"]] == ["b.md"]
