"""JWT-backed Goal scope and owner-isolation tests."""

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig

SECRET = "company-goals-isolation-tests"
OS_ID = "company-goals-tests"
ALL_SCOPES = ["goals:read", "goals:write", "goals:delete"]


def headers(user, scopes=None):
    token = jwt.encode(
        {
            "sub": user,
            "aud": OS_ID,
            "scopes": ALL_SCOPES if scopes is None else scopes,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
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
    response = client.post("/company/goals", json={"name": user, "user_id": "spoofed"}, headers=headers(user))
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == user
    return response.json()["id"]


def test_isolation_off_allows_scoped_readers_and_writers(make_client):
    c = make_client(False)
    a, b = create(c, "alice"), create(c, "bob")
    read = headers("reader", ["goals:read"])
    assert {p["id"] for p in c.get("/company/goals", headers=read).json()["data"]} == {a, b}
    assert c.get("/company/goals/" + a, headers=read).status_code == 200
    path = "/company/goals/" + a
    assert c.patch(path, json={"objective": "Updated", "user_id": "bob"}, headers=headers("bob")).status_code == 200
    assert c.get(path, headers=read).json()["user_id"] == "alice"
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200


def test_isolation_on_shares_reads_and_writes(make_client):
    c = make_client(True)
    a = create(c, "alice")
    own = {create(c, "bob") for _ in range(3)}
    # Reads are company-wide: bob sees alice's Goal alongside his own, paged over all four.
    pages = [c.get("/company/goals", params={"limit": 2, "page": p}, headers=headers("bob")).json() for p in (1, 2)]
    assert [len(p["data"]) for p in pages] == [2, 2]
    assert all(p["meta"]["total_count"] == 4 for p in pages)
    assert {row["id"] for p in pages for row in p["data"]} == own | {a}
    path = "/company/goals/" + a
    before = c.get(path, headers=headers("alice")).json()
    assert c.get(path, headers=headers("bob")).json() == before
    # Writes need the scope, not ownership: bob changes alice's Goal and the creator stays recorded.
    renamed = c.patch(path, json={"name": "renamed"}, headers=headers("bob"))
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed"
    assert renamed.json()["user_id"] == "alice"
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.get(path + "?include_deleted=true", headers=headers("bob")).status_code == 200
    assert c.get("/company/goals?include_deleted=true", headers=headers("bob")).json()["meta"]["total_count"] == 4
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200
    assert c.get(path, headers=headers("alice")).json()["user_id"] == "alice"


def test_admin_bypass_and_creator_attribution(make_client):
    c = make_client(True)
    a = create(c, "alice")
    admin = headers("admin", ["agent_os:admin"])
    path = "/company/goals/" + a
    assert c.get(path, headers=admin).status_code == 200
    assert c.patch(path, json={"name": "renamed"}, headers=admin).status_code == 200
    assert c.delete(path, headers=admin).status_code == 204
    assert c.post(path + "/restore", headers=admin).status_code == 200
    response = c.post("/company/goals", json={"name": "Admin goal", "user_id": "alice"}, headers=admin)
    assert response.status_code == 201
    assert response.json()["user_id"] == "admin"


@pytest.mark.parametrize("isolation", [False, True])
def test_scopes_apply_to_every_route(make_client, isolation):
    c = make_client(isolation)
    path = "/company/goals/" + create(c, "alice")
    for method, url, body, scopes in [
        ("get", "/company/goals", None, ["goals:write"]),
        ("get", path, None, ["goals:write"]),
        ("post", "/company/goals", {"name": "No"}, ["goals:read"]),
        ("patch", path, {"name": "No"}, ["goals:read"]),
        ("delete", path, None, ["goals:write"]),
        ("post", path + "/restore", None, ["goals:write"]),
    ]:
        assert c.request(method, url, json=body, headers=headers("alice", scopes)).status_code == 403
    assert c.get("/company/goals").status_code == 401


@pytest.mark.parametrize("authorization", [False, True])
def test_service_account_scopes_on_company_routes(tmp_path, authorization):
    import time

    from agno.os.service_accounts import generate_token

    db = SqliteDb(db_file=str(tmp_path / "service-accounts.db"))
    token, token_hash, token_prefix = generate_token()
    db.create_service_account(
        {
            "id": "reader-id",
            "name": "reader",
            "user_id": "admin",
            "token_hash": token_hash,
            "token_prefix": token_prefix,
            "scopes": ["goals:read"],
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
    assert client.get("/company/goals", headers=auth).status_code == 200
    assert client.post("/company/goals", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.patch("/company/goals/missing", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.delete("/company/goals/missing", headers=auth).status_code == 403
    assert client.post("/company/goals/missing/restore", headers=auth).status_code == 403

    from fastapi import HTTPException, Request

    from agno.os.auth import _authenticate_service_account

    request = Request({"type": "http", "app": app, "method": "POST", "path": "/company/goals", "headers": []})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_authenticate_service_account(request, token))
    assert exc.value.status_code == 403
    db.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_goal_scopes_catalog_is_opt_in(enabled, tmp_path):
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
    goals = {item["raw"] for item in response.json() if item["namespace"] == "goals"}
    assert goals == (set(ALL_SCOPES) if enabled else set())
