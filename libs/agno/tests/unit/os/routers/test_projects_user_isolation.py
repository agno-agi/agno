"""JWT-backed Project scope and owner-isolation tests."""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig

SECRET = "company-projects-isolation-tests"
OS_ID = "company-projects-tests"
ALL_SCOPES = ["projects:read", "projects:write", "projects:delete"]


def headers(user, scopes=None):
    token = jwt.encode(
        {
            "sub": user,
            "aud": OS_ID,
            "scopes": ALL_SCOPES if scopes is None else scopes,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def make_client(request, tmp_path):
    dbs = []

    def make(isolation):
        cls = AsyncSqliteDb if request.param else SqliteDb
        db = cls(db_file=str(tmp_path / (str(len(dbs)) + ".db")))
        dbs.append(db)
        return TestClient(
            AgentOS(
                id=OS_ID,
                db=db,
                company=CompanyConfig(),
                telemetry=False,
                authorization=True,
                authorization_config=AuthorizationConfig(
                    verification_keys=[SECRET], algorithm="HS256", user_isolation=isolation
                ),
            ).get_app()
        )

    yield make
    for db in dbs:
        if request.param:
            asyncio.run(db.close())
        else:
            db.close()


def create(client, user):
    parent = client.post("/company/products", json={"name": user}, headers=headers(user, ["products:write"])).json()[
        "id"
    ]
    response = client.post("/company/projects", json={"name": user, "product_id": parent}, headers=headers(user))
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == user
    return response.json()["id"]


def test_isolation_off_allows_scoped_readers_and_writers(make_client):
    c = make_client(False)
    a, b = create(c, "alice"), create(c, "bob")
    read = headers("reader", ["projects:read"])
    assert {p["id"] for p in c.get("/company/projects", headers=read).json()["data"]} == {a, b}
    assert c.get("/company/projects/" + a, headers=read).status_code == 200
    path = "/company/projects/" + a
    assert c.patch(path, json={"outcome": "Updated"}, headers=headers("bob")).status_code == 200
    assert c.get(path, headers=read).json()["user_id"] == "alice"
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200


def test_isolation_on_shares_reads_edits_and_deletion(make_client):
    c = make_client(True)
    a = create(c, "alice")
    own = {create(c, "bob") for _ in range(3)}
    pages = [
        c.get("/company/projects", params={"status": "proposed", "limit": 2, "page": p}, headers=headers("bob")).json()
        for p in (1, 2)
    ]
    assert [len(p["data"]) for p in pages] == [2, 2]
    assert all(p["meta"]["total_count"] == 4 for p in pages)
    assert {row["id"] for p in pages for row in p["data"]} == own | {a}
    path = "/company/projects/" + a
    before = c.get(path, headers=headers("alice")).json()
    assert c.get(path, headers=headers("bob")).json() == before
    edited = c.patch(path, json={"name": "Collaborative work"}, headers=headers("bob", ["projects:write"]))
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Collaborative work"
    assert edited.json()["user_id"] == "alice"
    # Archive and restore need the scope, not ownership; the creator stays recorded.
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.get(path + "?include_deleted=true", headers=headers("bob")).status_code == 200
    assert c.get("/company/projects?include_deleted=true", headers=headers("bob")).json()["meta"]["total_count"] == 4
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200
    assert c.get(path, headers=headers("alice")).json()["user_id"] == "alice"


def test_admin_bypass_and_creator_attribution(make_client):
    c = make_client(True)
    a = create(c, "alice")
    admin = headers("admin", ["agent_os:admin"])
    path = "/company/projects/" + a
    assert c.get(path, headers=admin).status_code == 200
    assert c.patch(path, json={"name": "renamed"}, headers=admin).status_code == 200
    assert c.delete(path, headers=admin).status_code == 204
    assert c.post(path + "/restore", headers=admin).status_code == 200
    parent = c.post("/company/products", json={"name": "Admin product"}, headers=admin).json()["id"]
    response = c.post("/company/projects", json={"name": "Admin work", "product_id": parent}, headers=admin)
    assert response.status_code == 201
    assert response.json()["user_id"] == "admin"


@pytest.mark.parametrize("isolation", [False, True])
def test_scopes_apply_to_every_route(make_client, isolation):
    c = make_client(isolation)
    path = "/company/projects/" + create(c, "alice")
    for method, url, body, scopes in [
        ("get", "/company/projects", None, ["projects:write"]),
        ("get", path, None, ["projects:write"]),
        ("post", "/company/projects", {"name": "No"}, ["projects:read"]),
        ("patch", path, {"name": "No"}, ["projects:read"]),
        ("delete", path, None, ["projects:write"]),
        ("post", path + "/restore", None, ["projects:write"]),
        ("post", path + "/transitions", {"target": "cancelled", "reason": "Stop"}, ["projects:read"]),
    ]:
        assert c.request(method, url, json=body, headers=headers("bob", scopes)).status_code == 403
    assert c.get("/company/projects").status_code == 401


@pytest.mark.parametrize("authorization", [False, True])
def test_service_account_scopes_on_company_routes(tmp_path, authorization):
    import time

    from agno.company import CompanyManager
    from agno.os.service_accounts import generate_token

    db = SqliteDb(db_file=str(tmp_path / "service-accounts.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Shared product", user_id="alice")
    shared = manager.create_project(product_id=product["id"], name="Shared work", user_id="alice")
    token, token_hash, token_prefix = generate_token()
    db.create_service_account(
        {
            "id": "reader-id",
            "name": "reader",
            "user_id": "admin",
            "token_hash": token_hash,
            "token_prefix": token_prefix,
            "scopes": ["projects:read"],
            "created_at": int(time.time()),
            "expires_at": None,
            "last_used_at": None,
            "revoked_at": None,
            "created_by": "admin",
        }
    )
    app = AgentOS(
        id=OS_ID,
        db=db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=authorization,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        if authorization
        else None,
    ).get_app()
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + token}
    assert client.get("/company/projects", headers=auth).status_code == 200
    assert client.get("/company/projects/" + shared["id"], headers=auth).status_code == 200
    assert client.get("/company/projects", headers=auth).json()["data"][0]["id"] == shared["id"]
    assert client.post("/company/projects", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.patch("/company/projects/missing", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.delete("/company/projects/missing", headers=auth).status_code == 403
    assert client.post("/company/projects/missing/restore", headers=auth).status_code == 403
    db.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_project_scopes_catalog_is_opt_in(enabled, tmp_path):
    from unittest.mock import MagicMock

    from agno.os.authz.admin_router import get_roles_router

    router = get_roles_router(MagicMock())
    db = SqliteDb(db_file=str(tmp_path / "catalog.db"))
    app = AgentOS(db=db, company=CompanyConfig() if enabled else None, telemetry=False).get_app()
    app.dependency_overrides[router.dependencies[0].dependency] = lambda: "admin"
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/authz/scopes")
    assert response.status_code == 200
    projects = {item["raw"] for item in response.json() if item["namespace"] == "projects"}
    assert projects == (set(ALL_SCOPES) if enabled else set())


@pytest.mark.parametrize("targets", [["active", "done"], ["cancelled"], ["active", "cancelled"]])
def test_collaborators_transition_projects_and_preserve_creator(make_client, targets):
    c = make_client(True)
    path = "/company/projects/" + create(c, "alice")
    for target in targets:
        response = c.post(
            path + "/transitions",
            json={"target": target, "reason": "Team decision"},
            headers=headers("bob", ["projects:write"]),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == target
        assert response.json()["user_id"] == "alice"
        assert response.json()["transitions"][-1]["user_id"] == "bob"
    assert (
        c.post(
            path + "/transitions",
            json={"target": "active", "reason": "Reopen"},
            headers=headers("bob", ["projects:write"]),
        ).status_code
        == 409
    )
