from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.registry import Registry

JWT_SECRET = "test-secret-for-filesystem-routes-32-bytes"
OS_ID = "filesystem-route-tests"


def _token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "aud": OS_ID,
            "scopes": ["agents:read"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


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


def test_config_describes_filesystem_and_returns_null_for_factory(tmp_path):
    db = SqliteDb(id="filesystem-db", db_file=str(tmp_path / "agent.db"))
    agent = Agent(id="notes", db=db, filesystem=True)
    factory = AgentFactory(
        id="factory-notes",
        db=db,
        factory=lambda ctx: Agent(id="factory-notes", db=db, filesystem=True),
    )
    client = _client(agent, factory, user_isolation=True)

    response = client.get("/config", headers=_headers("alice"))

    assert response.status_code == 200
    agents = {entry["id"]: entry for entry in response.json()["agents"]}
    assert agents["notes"]["filesystem"] == {
        "backend_type": "db",
        "db_id": "filesystem-db",
        "db_schema": None,
        "table_name": "agno_fs",
        "namespace_template": "users/{user_id}/agents/notes",
        "user_isolation": True,
        "max_file_bytes": 1_000_000,
        "max_namespace_bytes": 20_000_000,
    }
    assert agents["factory-notes"]["filesystem"] is None
