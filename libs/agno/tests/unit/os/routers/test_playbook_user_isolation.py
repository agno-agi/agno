"""Company-wide playbook reads and owner-scoped writes with authenticated callers."""

import asyncio
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig

SECRET = "company-playbook-test-key-long-enough"
SCOPES = [
    "products:read",
    "products:write",
    "products:delete",
    "wiki:read",
    "wiki:write",
    "decisions:read",
    "decisions:write",
    "tasks:read",
    "tasks:write",
    "projects:read",
    "projects:write",
]


def headers(user, scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "company-test",
                "exp": int(time.time()) + 300,
                "scopes": SCOPES if scopes is None else scopes,
            },
            SECRET,
            algorithm="HS256",
        )
    }


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def client(request, tmp_path):
    cls = AsyncSqliteDb if request.param else SqliteDb
    db = cls(db_file=str(tmp_path / "company.db"))
    os = AgentOS(
        id="company-test",
        db=db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", user_isolation=True),
    )
    with TestClient(os.get_app()) as client:
        yield client
    asyncio.run(db.close()) if request.param else db.close()


def test_wiki_shared_reads_writes_and_versions(client):
    product = client.post(
        "/company/products", json={"name": "SDK", "purpose": "Build"}, headers=headers("alice")
    ).json()
    url = "/company/products/" + product["id"] + "/wiki"
    listing = client.get(url, headers=headers("bob", ["wiki:read"]))
    assert listing.status_code == 200, listing.text
    assert {row["path"] for row in listing.json()["data"]} == {"brief.md", "status.md"}
    assert listing.json()["meta"]["total_count"] == 2
    assert client.get(url, headers=headers("bob", ["products:read"])).status_code == 403
    page = client.get(url + "/status.md", headers=headers("bob")).json()
    body = {"content": "Updated", "expected_version": page["metadata"]["version"]}
    # Writes need wiki:write, not Product ownership; the version check still serializes them.
    assert client.put(url + "/status.md", json=body, headers=headers("bob", ["wiki:read"])).status_code == 403
    assert client.put(url + "/status.md", json=body, headers=headers("bob")).status_code == 200
    assert client.put(url + "/status.md", json=body, headers=headers("alice")).status_code == 409
    assert client.get(url + "/status.md", headers=headers("bob")).json()["content"] == "Updated"
    assert (
        client.put(
            url + "/brief.md", json={"content": "Human brief", "expected_version": 1}, headers=headers("alice")
        ).status_code
        == 200
    )
    assert (
        client.put(
            url + "/notes.md", json={"content": "new", "expected_version": 0}, headers=headers("alice")
        ).status_code
        == 200
    )
    assert (
        client.put(
            url + "/notes.md", json={"content": "lost", "expected_version": 0}, headers=headers("alice")
        ).status_code
        == 409
    )
    assert client.get(url + "/missing.md", headers=headers("alice")).status_code == 404
    assert client.get("/company/products/missing/wiki", headers=headers("alice")).status_code == 404
    assert client.get(url + "/bad.txt", headers=headers("alice")).status_code == 422
    assert client.put(url + "/status.md", json={"content": "unguarded"}, headers=headers("alice")).status_code == 422
    assert client.delete("/company/products/" + product["id"], headers=headers("alice")).status_code == 204
    assert client.get(url, headers=headers("alice")).status_code == 404
    assert client.post("/company/products/" + product["id"] + "/restore", headers=headers("alice")).status_code == 200
    assert client.get(url + "/status.md", headers=headers("bob")).json()["content"] == "Updated"


def test_company_namespace_and_decision_identity(client):
    assert client.get("/company/wiki", headers=headers("reader")).status_code == 200
    # Company pages are shared: members with wiki:write edit them, as admins do.
    body = {"content": "shared", "expected_version": 1}
    assert client.put("/company/wiki/status.md", json=body, headers=headers("alice")).status_code == 200
    body = {"content": "admin edit", "expected_version": 2}
    assert (
        client.put("/company/wiki/status.md", json=body, headers=headers("admin", ["agent_os:admin"])).status_code
        == 200
    )
    for user in ["alice", "bob"]:
        response = client.post(
            "/company/decisions",
            json={"decision": "Ship " + user, "reasoning": "tested", "outcome": "approved"},
            headers=headers(user),
        )
        assert response.status_code == 201, response.text
        assert response.json()["user_id"] == user
    response = client.get("/company/decisions?limit=1&page=2", headers=headers("reader", ["decisions:read"]))
    assert response.status_code == 200 and response.json()["meta"]["total_count"] == 2
    assert len(response.json()["data"]) == 1
    assert client.get("/company/decisions?query=bob", headers=headers("reader")).json()["meta"]["total_count"] == 1
    assert (
        client.post(
            "/company/decisions", json={"decision": "spoof", "user_id": "admin"}, headers=headers("bob")
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/company/decisions", json={"decision": "no"}, headers=headers("reader", ["decisions:read"])
        ).status_code
        == 403
    )
    assert "decisions.md" not in {
        row["path"] for row in client.get("/company/wiki", headers=headers("reader")).json()["data"]
    }


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/company/products/p1/wiki", ["wiki:read"]),
        ("GET", "/company/products/p1/wiki/notes/status.md", ["wiki:read"]),
        ("PUT", "/company/products/p1/wiki/status.md", ["wiki:write"]),
        ("GET", "/company/products/p1", ["products:read"]),
    ],
)
def test_wiki_scope_precedes_generic_product_pattern(method, path, expected):
    from agno.os.scopes import get_default_scope_mappings, get_required_scopes_for_route

    assert get_required_scopes_for_route(get_default_scope_mappings(company=True), method, path) == expected
