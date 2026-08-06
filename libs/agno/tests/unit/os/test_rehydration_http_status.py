"""A component whose references cannot be rehydrated answers 422 over HTTP.

Covers both deployment shapes: an AgentOS that owns its FastAPI app, and one
mounted on an app the caller supplied, where AgentOS registers no exception
handlers of its own.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.team.team import Team


def _search(query: str) -> str:
    """Search for a query."""
    return f"results for {query}"


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "rehydration_status.db"))


@pytest.fixture
def toolless_os(db):
    """An AgentOS whose registry lacks the tool its stored components reference."""
    # Tools reach the stored config only when the component carries a model.
    model = OpenAIChat(id="gpt-4o-mini")
    Agent(id="broken-agent", name="Broken", model=model, tools=[_search]).save(db=db)
    Agent(id="clean-agent", name="Clean", model=model).save(db=db)
    Team(id="broken-team", name="BrokenTeam", model=model, members=[], tools=[_search]).save(db=db)
    return AgentOS(id="status-os", db=db, registry=Registry(dbs=[db]))


def _client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestRehydrationHttpStatus:
    def test_detail_read_of_a_broken_component_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        response = client.get("/agents/broken-agent")

        assert response.status_code == 422
        assert "search" in response.json()["detail"]

    def test_broken_team_detail_read_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        assert client.get("/teams/broken-team").status_code == 422

    def test_dispatch_of_a_broken_component_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        response = client.post("/agents/broken-agent/runs", data={"message": "hi", "stream": "false"})

        assert response.status_code == 422

    def test_intact_component_and_missing_component_are_unaffected(self, toolless_os):
        client = _client(toolless_os.get_app())

        assert client.get("/agents/clean-agent").status_code == 200
        assert client.get("/agents/does-not-exist").status_code == 404
        # Listings stay readable so a broken component remains discoverable.
        assert client.get("/agents").status_code == 200

    def test_422_survives_a_caller_supplied_app(self, db):
        """AgentOS registers its exception handlers only when it owns the app,
        so the status has to come from the router rather than a handler."""
        model = OpenAIChat(id="gpt-4o-mini")
        Agent(id="broken-agent", name="Broken", model=model, tools=[_search]).save(db=db)
        mounted = AgentOS(id="mounted-os", db=db, registry=Registry(dbs=[db]), base_app=FastAPI())
        client = _client(mounted.get_app())

        response = client.get("/agents/broken-agent")

        assert response.status_code == 422
        assert "search" in response.json()["detail"]
