"""Company details REST permissions, conflict behavior and manager context."""

import time

import jwt
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, Authorization, CompanyConfig

SECRET = "company-details-offline-test-key-32-characters"


def headers(scopes):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "alice", "aud": "details-test", "scopes": scopes, "exp": time.time() + 600},
            SECRET,
            algorithm="HS256",
        )
    }


def test_details_permissions_edits_and_restart(tmp_path):
    db_file = str(tmp_path / "company.db")
    db = SqliteDb(db_file=db_file)
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="details-test")
    os = AgentOS(id="details-test", db=db, company=CompanyConfig(name="Initial"), authorization=auth, telemetry=False)
    client = TestClient(os.get_app())
    assert client.get("/company/details", headers=headers([])).status_code == 403
    read = client.get("/company/details", headers=headers(["company:read"]))
    assert read.status_code == 200
    assert client.get("/company/details/access", headers=headers(["company:read"])).json() == {"can_edit": False}
    assert client.get("/company/details/access", headers=headers(["agent_os:admin"])).json() == {"can_edit": True}
    data = read.json()
    body = {"expected_updated_at": data["updated_at"], "name": "Edited", "description": "Human identity"}
    assert (
        client.patch("/company/details", json=body, headers=headers(["company:read", "products:write"])).status_code
        == 403
    )
    edited = client.patch("/company/details", json=body, headers=headers(["agent_os:admin"]))
    assert edited.status_code == 200
    assert client.patch("/company/details", json=body, headers=headers(["agent_os:admin"])).status_code == 409
    assert (
        client.patch("/company/details", json={**body, "name": None}, headers=headers(["agent_os:admin"])).status_code
        == 422
    )
    db.close()
    fresh_db = SqliteDb(db_file=db_file)
    restarted = AgentOS(
        id="details-test", db=fresh_db, company=CompanyConfig(name="Deployment"), authorization=auth, telemetry=False
    )
    fresh = TestClient(restarted.get_app()).get("/company/details", headers=headers(["company:read"]))
    assert fresh.json() == edited.json()
    fresh_db.close()


def test_database_scope_isolated(tmp_path):
    path = str(tmp_path / "shared.db")
    first = SqliteDb(db_file=path, products_table="first_products")
    second = SqliteDb(db_file=path, products_table="second_products")
    first.initialize_company("First")
    second.initialize_company("Second")
    assert first.get_company()["name"] == "First"
    assert second.get_company()["name"] == "Second"
    first.close()
    second.close()


def test_next_manager_runs_use_saved_details_without_products(tmp_path):
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse
    from agno.os import OSManager
    from agno.registry._reserved import COMPANY_MANAGER_ID, MANAGER_TEAM_ID

    class ContextModel(Model):
        def __init__(self):
            super().__init__(id="company-context-offline", provider="test")

        def invoke(self, messages, *args, **kwargs):
            context = "\n".join(str(message.content) for message in messages if message.role == "system")
            return ModelResponse(
                role="assistant",
                content="new description"
                if "new description" in context
                else "original description"
                if "original description" in context
                else "no company context",
                response_usage=MessageMetrics(),
            )

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        async def ainvoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

    db = SqliteDb(db_file=str(tmp_path / "manager.db"))
    model = ContextModel()
    os = AgentOS(
        id="details-test",
        db=db,
        company=CompanyConfig(model=model, description="original description"),
        manager=OSManager(model=model, access_docs=False, offload_tool_results=False),
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="details-test"),
        telemetry=False,
    )
    client = TestClient(os.get_app())
    admin = headers(["agent_os:admin"])
    data = client.get("/company/details", headers=admin).json()
    for component_type, component_id in [("agents", COMPANY_MANAGER_ID), ("teams", MANAGER_TEAM_ID)]:
        scope = f"{component_type}:{component_id}:run"
        first = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=headers([scope, "company:read"]),
        )
        assert first.status_code == 200, first.text
        assert first.json()["content"] == "original description"
        denied = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=headers([scope]),
        )
        assert denied.status_code == 200, denied.text
        assert denied.json()["content"] == "no company context"
    changed = client.patch(
        "/company/details",
        json={"expected_updated_at": data["updated_at"], "description": "new description"},
        headers=admin,
    )
    assert changed.status_code == 200
    for component_type, component_id in [("agents", COMPANY_MANAGER_ID), ("teams", MANAGER_TEAM_ID)]:
        updated = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=admin,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["content"] == "new description"
    db.close()
