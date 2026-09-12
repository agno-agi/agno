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

    assert client.get("/files").status_code == 401
    assert client.get("/agents/notes/files").status_code == 401

    listed = client.get("/agents/notes/files", headers=_headers("alice"))
    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["notes"]

    content = client.get(
        "/agents/notes/files/content",
        params={"path": "notes/state.md"},
        headers=_headers("alice"),
    )
    assert content.status_code == 200
    assert content.json()["content"] == "alpha needle\nbeta\n"

    search = client.get(
        "/agents/notes/files/search",
        params={"query": "needle"},
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

    listed = client.get("/files", headers=_headers("alice"))
    searched = client.get("/files", params={"query": "needle"}, headers=_headers("alice"))
    filtered = client.get("/files", params={"agent_id": "reports"}, headers=_headers("alice"))

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

    response = client.get("/files", headers=_headers("alice"))
    list_files.assert_awaited_once()
    searched = client.get("/files", params={"query": "shared"}, headers=_headers("alice"))
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

    restricted = client.get("/files", headers=_scoped_headers("alice", ["agents:one:read"]))
    assert restricted.status_code == 200
    assert restricted.json()["entries"][0]["agent_ids"] == ["one"]


def test_global_files_skips_remote_agents_but_explicit_requests_fail(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(db, namespace="notes")
    filesystem.write("state.md", "local")
    agent = Agent(id="notes", db=db, filesystem=filesystem)
    remote = RemoteAgent(base_url="http://localhost:9999", agent_id="remote")
    client = _client(agent, remote)

    listed = client.get("/files", headers=_headers("alice"))
    explicit = client.get("/files", params={"agent_id": "remote"}, headers=_headers("alice"))

    assert listed.status_code == 200
    assert [entry["path"] for entry in listed.json()["entries"]] == ["state.md"]
    assert explicit.status_code == 501


def test_global_files_rejects_empty_scopes(tmp_path):
    agent = Agent(id="notes", db=SqliteDb(db_file=str(tmp_path / "agents.db")), filesystem=True)
    client = _client(agent)

    response = client.get("/files", headers=_scoped_headers("alice", []))

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
    listed = client.get("/files", params={"namespace": resolved_namespace}, headers=_headers("Alice"))

    assert listed.status_code == 200
    assert [(entry["namespace"], entry["path"]) for entry in listed.json()["entries"]] == [
        (resolved_namespace, "state.md")
    ]
    if namespace != "My Namespace":
        other_user = client.get("/files", params={"namespace": resolved_namespace}, headers=_headers("alice"))
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
        "/files",
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

    assert client.get("/agents/notes/files").status_code == 401

    upper = client.get(
        "/agents/notes/files/content", params={"path": "private.md"}, headers=_headers("Alice")
    )
    lower = client.get(
        "/agents/notes/files/content", params={"path": "private.md"}, headers=_headers("alice")
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
        "/agents/notes/files/content",
        params={"path": "state.md"},
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

    response = client.get("/agents/notes/files", headers=_headers("alice"))

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
        "/agents/factory-notes/files/content",
        params={"path": "state.md"},
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
        "/agents/stored-notes/files/content",
        params={"path": "state.md"},
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
        "/agents/notes/files/content",
        params={"path": "large.md", "limit": 4},
        headers=_headers("alice"),
    )
    second = client.get(
        "/agents/notes/files/content",
        params={"path": "large.md", "offset": first.json()["next_offset"], "limit": 4},
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
                "db_schema": None,
                "table_name": "agno_fs",
                "namespace": "users/alice/notes",
                "user_isolation": True,
                "max_file_bytes": 1_000_000,
                "max_namespace_bytes": 20_000_000,
                "agents": ["notes"],
            }
        ]
    }
    assert "filesystem" not in agents["notes"]
    assert "filesystem" not in agents["factory-notes"]
