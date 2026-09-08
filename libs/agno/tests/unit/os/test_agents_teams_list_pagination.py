from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.teams.schema import TeamResponse
from agno.team import Team


def make_client(resource_type, count):
    if resource_type == "agents":
        resources = [Agent(id=f"agent-{i}", name=f"Agent {i}") for i in range(count)]
        os = AgentOS(
            agents=resources,
            teams=None if resources else [Team(id="sentinel-team", name="Sentinel Team", members=[])],
            telemetry=False,
        )
    else:
        resources = [Team(id=f"team-{i}", name=f"Team {i}", members=[]) for i in range(count)]
        os = AgentOS(
            agents=None if resources else [Agent(id="sentinel-agent", name="Sentinel Agent")],
            teams=resources,
            telemetry=False,
        )
    return SimpleNamespace(client=TestClient(os.get_app()), resources=resources)


def assert_meta(body, **expected):
    assert {key: body["meta"][key] for key in expected} == expected


@pytest.mark.parametrize("resource_type", ["agents", "teams"])
class TestListPagination:
    def test_default_first_page(self, resource_type):
        harness = make_client(resource_type, 25)

        response = harness.client.get(f"/{resource_type}")

        assert response.status_code == 200
        body = response.json()
        assert [item["id"] for item in body["data"]] == [f"{resource_type[:-1]}-{i}" for i in range(20)]
        assert_meta(body, page=1, limit=20, total_pages=2, total_count=25)

    def test_page_beyond_range_returns_empty_data(self, resource_type):
        harness = make_client(resource_type, 3)

        response = harness.client.get(f"/{resource_type}", params={"limit": 2, "page": 3})

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert_meta(body, page=3, limit=2, total_pages=2, total_count=3)

    def test_limit_upper_bound(self, resource_type):
        harness = make_client(resource_type, 1)

        response = harness.client.get(f"/{resource_type}", params={"limit": 1000})

        assert response.status_code == 200
        assert response.json()["meta"]["limit"] == 1000
        assert harness.client.get(f"/{resource_type}", params={"limit": 1001}).status_code == 422

    def test_empty_list(self, resource_type):
        harness = make_client(resource_type, 0)

        response = harness.client.get(f"/{resource_type}")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert_meta(body, page=1, limit=20, total_pages=0, total_count=0)

    def test_non_default_page_only_serializes_current_page(self, resource_type, monkeypatch):
        harness = make_client(resource_type, 5)
        serialized_ids = []

        if resource_type == "agents":

            async def from_agent(cls, agent, is_component=False):
                serialized_ids.append(agent.id)
                return AgentResponse(id=agent.id, name=agent.name, is_component=is_component)

            monkeypatch.setattr(AgentResponse, "from_agent", classmethod(from_agent))
        else:

            async def from_team(cls, team, is_component=False):
                serialized_ids.append(team.id)
                return TeamResponse(id=team.id, name=team.name, is_component=is_component)

            monkeypatch.setattr(TeamResponse, "from_team", classmethod(from_team))

        response = harness.client.get(f"/{resource_type}", params={"limit": 2, "page": 2})

        assert response.status_code == 200
        expected_ids = [f"{resource_type[:-1]}-2", f"{resource_type[:-1]}-3"]
        assert [item["id"] for item in response.json()["data"]] == expected_ids
        assert serialized_ids == expected_ids
        assert_meta(response.json(), page=2, limit=2, total_pages=3, total_count=5)
