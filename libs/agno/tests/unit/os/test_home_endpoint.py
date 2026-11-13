"""Tests for the GET / landing route.

The root returns a tiny, stable JSON response pointing at the real endpoints:
/docs (when enabled) for exploration, /info for machine-readable metadata,
/health for probes. It is not part of the API contract and is excluded from
the OpenAPI schema.
"""

from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings


def _build_client(**kwargs) -> TestClient:
    agent = Agent(name="Home Agent", id="home-agent", telemetry=False)
    os_instance = AgentOS(agents=[agent], telemetry=False, **kwargs)
    return TestClient(os_instance.get_app())


def test_returns_landing_links_by_default():
    client = _build_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "AgentOS",
        "health": "/health",
        "info": "/info",
        "docs": "/docs",
    }


def test_omits_docs_link_when_docs_disabled():
    client = _build_client(settings=AgnoAPISettings(docs_enabled=False))
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"name": "AgentOS", "health": "/health", "info": "/info"}


def test_returns_os_name():
    client = _build_client(name="Customer Support")
    body = client.get("/").json()
    assert body["name"] == "Customer Support"


def test_home_stays_unauthenticated_with_security_key():
    client = _build_client(settings=AgnoAPISettings(os_security_key="test-key"))
    response = client.get("/")
    assert response.status_code == 200


def test_home_excluded_from_openapi_schema():
    client = _build_client()
    schema = client.get("/openapi.json").json()
    assert "/" not in schema["paths"]
