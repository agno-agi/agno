"""GET /registry lists only the entries the caller is authorized to read."""

from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, Authorization
from agno.os.scopes import get_resource_context_from_path
from agno.registry import Registry

JWT_SECRET = "test-secret-key-at-least-256-bits-long-000"
OS_ID = "registry-access-test-os"


def search(query: str) -> str:
    """Search the web."""
    return query


def sql(query: str) -> str:
    """Run a SQL query."""
    return query


def slack(message: str) -> str:
    """Post to Slack."""
    return message


def _token(scopes: Optional[List[str]] = None, org_id: Optional[str] = None, sub: str = "user") -> str:
    payload: Dict[str, Any] = {
        "sub": sub,
        "aud": OS_ID,
        "scopes": scopes or [],
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _os(**kwargs: Any) -> AgentOS:
    return AgentOS(
        id=OS_ID,
        agents=[Agent(id="support-agent", name="Support Agent")],
        registry=Registry(tools=[search, sql, slack]),
        telemetry=False,
        **kwargs,
    )


def _list(client: TestClient, token: Optional[str] = None, resource_type: str = "tool"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/registry", params={"resource_type": resource_type}, headers=headers)


def _names(client: TestClient, token: Optional[str] = None, resource_type: str = "tool") -> List[str]:
    response = _list(client, token, resource_type)
    assert response.status_code == 200, response.text
    return sorted(item["name"] for item in response.json()["data"])


@pytest.fixture
def scope_client() -> TestClient:
    authorization = Authorization(
        verification_keys=[JWT_SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID
    )
    return TestClient(_os(authorization=authorization).get_app())


class TestTokenScopes:
    def test_the_collection_scope_lists_everything(self, scope_client):
        assert _names(scope_client, _token(["registry:read"])) == ["search", "slack", "sql"]

    def test_an_entry_scope_lists_only_that_entry(self, scope_client):
        assert _names(scope_client, _token(["registry:search:read"])) == ["search"]
        assert _names(scope_client, _token(["registry:search:read", "registry:sql:read"])) == ["search", "sql"]

    def test_the_wildcard_scope_lists_everything(self, scope_client):
        assert _names(scope_client, _token(["registry:*:read"])) == ["search", "slack", "sql"]

    def test_the_admin_scope_lists_everything(self, scope_client):
        assert _names(scope_client, _token(["agent_os:admin"])) == ["search", "slack", "sql"]

    def test_a_caller_with_no_registry_scope_sees_nothing(self, scope_client):
        assert _names(scope_client, _token(["agents:read"])) == []

    def test_the_total_count_does_not_reveal_hidden_entries(self, scope_client):
        response = _list(scope_client, _token(["registry:search:read"]))
        assert response.json()["meta"]["total_count"] == 1

    def test_an_entry_is_granted_by_its_id(self, scope_client):
        token = _token(["registry:support-agent:read"])
        assert _names(scope_client, token, resource_type="agent") == ["Support Agent"]
        assert _names(scope_client, token) == []


class TestWithoutAuthorization:
    def test_an_open_os_lists_everything(self):
        client = TestClient(_os().get_app())
        assert _names(client) == ["search", "slack", "sql"]


class TestTenantRoles:
    @pytest.fixture
    def authz(self, tmp_path) -> Authorization:
        authz = Authorization(
            db=SqliteDb(db_file=str(tmp_path / "authz.db")),
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            roles_claim="org_id",
            trust_token_scopes=True,
        )
        authz.define_role("acme", ["registry:read"])
        authz.define_role("globex", ["registry:search:read"])
        return authz

    @pytest.fixture
    def client(self, authz) -> TestClient:
        return TestClient(_os(authorization=authz).get_app())

    def test_each_tenant_sees_what_its_role_grants(self, client):
        assert _names(client, _token(org_id="acme")) == ["search", "slack", "sql"]
        assert _names(client, _token(org_id="globex")) == ["search"]

    def test_an_unknown_tenant_sees_nothing(self, client):
        assert _names(client, _token(org_id="initech")) == []
        assert _names(client, _token()) == []

    def test_a_role_change_applies_to_the_next_listing(self, client):
        admin = {"Authorization": f"Bearer {_token(['agent_os:admin'], sub='operator')}"}
        response = client.put(
            "/authz/roles/globex/scopes",
            headers=admin,
            json={"scopes": ["registry:search:read", "registry:sql:read"]},
        )
        assert response.status_code == 200, response.text
        assert _names(client, _token(org_id="globex")) == ["search", "sql"]

    def test_a_tenant_is_onboarded_through_the_roles_api(self, client):
        admin = {"Authorization": f"Bearer {_token(['agent_os:admin'], sub='operator')}"}
        assert client.post("/authz/roles", headers=admin, json={"slug": "initech"}).status_code == 201
        response = client.put("/authz/roles/initech/scopes", headers=admin, json={"scopes": ["registry:slack:read"]})
        assert response.status_code == 200, response.text
        assert _names(client, _token(org_id="initech")) == ["slack"]

    def test_a_tenant_cannot_change_its_own_role(self, client):
        headers = {"Authorization": f"Bearer {_token(org_id='globex')}"}
        response = client.put("/authz/roles/globex/scopes", headers=headers, json={"scopes": ["registry:read"]})
        assert response.status_code == 403


class TestResourceContext:
    def test_the_registry_listing_is_a_resource_collection(self):
        assert get_resource_context_from_path("/registry") == ("registry", None)

    def test_other_paths_are_unchanged(self):
        assert get_resource_context_from_path("/agents/my-agent/runs") == ("agents", "my-agent")
        assert get_resource_context_from_path("/sessions") == (None, None)
        assert get_resource_context_from_path("/knowledge/registry") == (None, None)
