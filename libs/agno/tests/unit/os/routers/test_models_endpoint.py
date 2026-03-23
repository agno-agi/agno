"""Unit tests for the /models endpoint.

Verifies that models declared in the AgentOS YAML config's
``available_models`` list are exposed through the GET /models endpoint.

Regression test for https://github.com/agno-agi/agno/issues/7060.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.config import AgentOSConfig
from agno.os.router import get_agentOS_router
from agno.os.settings import AgnoAPISettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_os(
    agents=None,
    teams=None,
    config=None,
    interfaces=None,
    storage=None,
):
    """Return a minimal mock AgentOS object."""
    os_mock = MagicMock()
    os_mock.agents = agents or []
    os_mock.teams = teams or []
    os_mock.config = config
    os_mock.interfaces = interfaces or []
    os_mock.storage = storage
    return os_mock


def _make_test_client(agent_os) -> TestClient:
    app = FastAPI()
    router = get_agentOS_router(agent_os, AgnoAPISettings())
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModelsEndpoint:
    """Tests for GET /models."""

    def test_empty_config_returns_empty_list(self):
        """No agents, no teams, no config → empty model list."""
        client = _make_test_client(_make_agent_os())
        resp = client.get("/models")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_available_models_from_config_included(self):
        """Models in config.available_models appear in /models response.

        This is the core regression case for issue #7060: previously the
        endpoint ignored available_models and always returned an empty list
        when no agents/teams were registered.
        """
        cfg = AgentOSConfig(available_models=["gpt-4o", "claude-3-7-sonnet"])
        client = _make_test_client(_make_agent_os(config=cfg))

        resp = client.get("/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert "gpt-4o" in ids
        assert "claude-3-7-sonnet" in ids

    def test_agent_models_still_included(self):
        """Models from registered agents are still present alongside config models."""
        cfg = AgentOSConfig(available_models=["extra-model"])

        agent = MagicMock()
        agent.model = MagicMock()
        agent.model.id = "gpt-4o-mini"
        agent.model.provider = "openai"

        client = _make_test_client(_make_agent_os(agents=[agent], config=cfg))

        resp = client.get("/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert "gpt-4o-mini" in ids
        assert "extra-model" in ids

    def test_no_duplicate_models(self):
        """A model present both in an agent and in available_models is listed once."""
        cfg = AgentOSConfig(available_models=["gpt-4o-mini"])

        agent = MagicMock()
        agent.model = MagicMock()
        agent.model.id = "gpt-4o-mini"
        agent.model.provider = "openai"

        client = _make_test_client(_make_agent_os(agents=[agent], config=cfg))

        resp = client.get("/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert ids.count("gpt-4o-mini") == 1

    def test_config_none_does_not_raise(self):
        """When config is None the endpoint returns models from agents only."""
        agent = MagicMock()
        agent.model = MagicMock()
        agent.model.id = "gpt-4o"
        agent.model.provider = "openai"

        client = _make_test_client(_make_agent_os(agents=[agent], config=None))

        resp = client.get("/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert "gpt-4o" in ids
