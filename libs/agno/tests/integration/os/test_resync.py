"""Integration tests for AgentOS resync functionality."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(name="test-agent", id="test-agent-id", db=InMemoryDb())


@pytest.fixture
def second_agent():
    """Create a second test agent to be added during lifespan."""
    return Agent(name="second-agent", id="second-agent-id", db=InMemoryDb())


@pytest.fixture
def test_team(test_agent: Agent):
    """Create a test team."""
    return Team(name="test-team", id="test-team-id", members=[test_agent])


@pytest.fixture
def second_team():
    """Create a second test team to be added during lifespan."""
    member = Agent(name="second-team-member", id="second-team-member-id")
    return Team(name="second-team", id="second-team-id", members=[member])


@pytest.fixture
def test_workflow():
    """Create a test workflow."""
    return Workflow(name="test-workflow", id="test-workflow-id")


@pytest.fixture
def second_workflow():
    """Create a second test workflow to be added during lifespan."""
    return Workflow(name="second-workflow", id="second-workflow-id")


class TestResyncPreservesEndpoints:
    """Tests to verify that resync preserves and restores all endpoints."""

    def test_resync_preserves_health_endpoint(self, test_agent: Agent):
        """Test that resync preserves the health endpoint."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        # Verify health endpoint works before resync
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

            # Perform resync
            agent_os.resync(app=app)

            # Verify health endpoint still works after resync
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

    def test_resync_preserves_home_endpoint(self, test_agent: Agent):
        """Test that resync preserves the home endpoint."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify home endpoint works before resync
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert "name" in data
            assert "AgentOS API" in data["name"]

            # Perform resync
            agent_os.resync(app=app)

            # Verify home endpoint still works after resync
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert "name" in data
            assert "AgentOS API" in data["name"]

    def test_resync_preserves_config_endpoint(self, test_agent: Agent):
        """Test that resync preserves the config endpoint."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify config endpoint works before resync
            response = client.get("/config")
            assert response.status_code == 200

            # Perform resync
            agent_os.resync(app=app)

            # Verify config endpoint still works after resync
            response = client.get("/config")
            assert response.status_code == 200

    def test_resync_preserves_sessions_endpoint(self, test_agent: Agent):
        """Test that resync preserves the sessions endpoint."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify sessions endpoint exists before resync
            response = client.get("/sessions")
            assert response.status_code == 200

            # Perform resync
            agent_os.resync(app=app)

            # Verify sessions endpoint still exists after resync
            response = client.get("/sessions")
            assert response.status_code == 200

    def test_resync_preserves_agents_endpoint(self, test_agent: Agent):
        """Test that resync preserves the agents endpoint."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify agents endpoint works before resync
            response = client.get("/agents")
            assert response.status_code == 200
            agents_before = response.json()
            assert len(agents_before) == 1

            # Perform resync
            agent_os.resync(app=app)

            # Verify agents endpoint still works after resync
            response = client.get("/agents")
            assert response.status_code == 200
            agents_after = response.json()
            assert len(agents_after) == 1

    def test_resync_preserves_teams_endpoint(self, test_agent: Agent, test_team: Team):
        """Test that resync preserves the teams endpoint."""
        agent_os = AgentOS(agents=[test_agent], teams=[test_team])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify teams endpoint works before resync
            response = client.get("/teams")
            assert response.status_code == 200
            teams_before = response.json()
            assert len(teams_before) == 1

            # Perform resync
            agent_os.resync(app=app)

            # Verify teams endpoint still works after resync
            response = client.get("/teams")
            assert response.status_code == 200
            teams_after = response.json()
            assert len(teams_after) == 1

    def test_resync_preserves_workflows_endpoint(self, test_agent: Agent, test_workflow: Workflow):
        """Test that resync preserves the workflows endpoint."""
        agent_os = AgentOS(agents=[test_agent], workflows=[test_workflow])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify workflows endpoint works before resync
            response = client.get("/workflows")
            assert response.status_code == 200
            workflows_before = response.json()
            assert len(workflows_before) == 1

            # Perform resync
            agent_os.resync(app=app)

            # Verify workflows endpoint still works after resync
            response = client.get("/workflows")
            assert response.status_code == 200
            workflows_after = response.json()
            assert len(workflows_after) == 1

    def test_resync_preserves_all_core_endpoints(self, test_agent: Agent, test_team: Team, test_workflow: Workflow):
        """Test that resync preserves all core endpoints."""
        agent_os = AgentOS(agents=[test_agent], teams=[test_team], workflows=[test_workflow])
        app = agent_os.get_app()

        core_endpoints = [
            "/",
            "/health",
            "/config",
            "/agents",
            "/teams",
            "/workflows",
            "/sessions",
        ]

        with TestClient(app) as client:
            # Verify all core endpoints work before resync
            for endpoint in core_endpoints:
                response = client.get(endpoint)
                assert response.status_code == 200, f"Endpoint {endpoint} failed before resync"

            # Perform resync
            agent_os.resync(app=app)

            # Verify all core endpoints still work after resync
            for endpoint in core_endpoints:
                response = client.get(endpoint)
                assert response.status_code == 200, f"Endpoint {endpoint} failed after resync"


class TestResyncWithLifespanAdditions:
    """Tests to verify that resync picks up agents/teams/workflows added during lifespan."""

    def test_resync_picks_up_agent_added_in_lifespan(self, test_agent: Agent, second_agent: Agent):
        """Test that resync picks up an agent added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new agent
            agent_os.agents.append(second_agent)

            # Resync the AgentOS to pick up the new agent
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify both agents are now available
            response = client.get("/agents")
            assert response.status_code == 200
            agents = response.json()
            assert len(agents) == 2

            agent_ids = [agent["id"] for agent in agents]
            assert "test-agent-id" in agent_ids
            assert "second-agent-id" in agent_ids

    def test_resync_picks_up_team_added_in_lifespan(self, test_agent: Agent, test_team: Team, second_team: Team):
        """Test that resync picks up a team added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new team
            agent_os.teams.append(second_team)

            # Resync the AgentOS to pick up the new team
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], teams=[test_team], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify both teams are now available
            response = client.get("/teams")
            assert response.status_code == 200
            teams = response.json()
            assert len(teams) == 2

            team_ids = [team["id"] for team in teams]
            assert "test-team-id" in team_ids
            assert "second-team-id" in team_ids

    def test_resync_picks_up_workflow_added_in_lifespan(
        self, test_agent: Agent, test_workflow: Workflow, second_workflow: Workflow
    ):
        """Test that resync picks up a workflow added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new workflow
            agent_os.workflows.append(second_workflow)

            # Resync the AgentOS to pick up the new workflow
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], workflows=[test_workflow], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify both workflows are now available
            response = client.get("/workflows")
            assert response.status_code == 200
            workflows = response.json()
            assert len(workflows) == 2

            workflow_ids = [workflow["id"] for workflow in workflows]
            assert "test-workflow-id" in workflow_ids
            assert "second-workflow-id" in workflow_ids

    def test_resync_picks_up_multiple_entities_added_in_lifespan(
        self,
        test_agent: Agent,
        second_agent: Agent,
        test_team: Team,
        second_team: Team,
        test_workflow: Workflow,
        second_workflow: Workflow,
    ):
        """Test that resync picks up multiple entities added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add multiple new entities
            agent_os.agents.append(second_agent)
            agent_os.teams.append(second_team)
            agent_os.workflows.append(second_workflow)

            # Resync the AgentOS to pick up all new entities
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(
            agents=[test_agent],
            teams=[test_team],
            workflows=[test_workflow],
            lifespan=lifespan,
        )
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify all agents are available
            response = client.get("/agents")
            assert response.status_code == 200
            agents = response.json()
            assert len(agents) == 2

            # Verify all teams are available
            response = client.get("/teams")
            assert response.status_code == 200
            teams = response.json()
            assert len(teams) == 2

            # Verify all workflows are available
            response = client.get("/workflows")
            assert response.status_code == 200
            workflows = response.json()
            assert len(workflows) == 2

    def test_home_endpoint_works_after_lifespan_resync(self, test_agent: Agent, second_agent: Agent):
        """Test that home (/) endpoint works after resync during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new agent
            agent_os.agents.append(second_agent)

            # Resync the AgentOS to pick up the new agent
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify home endpoint works after resync
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert "name" in data
            assert "AgentOS API" in data["name"]

    def test_new_agent_endpoint_available_after_resync(self, test_agent: Agent, second_agent: Agent):
        """Test that individual agent endpoint is available for agents added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new agent
            agent_os.agents.append(second_agent)

            # Resync the AgentOS to pick up the new agent
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify the new agent's individual endpoint is accessible
            response = client.get(f"/agents/{second_agent.id}")
            assert response.status_code == 200
            agent_data = response.json()
            assert agent_data["id"] == "second-agent-id"
            assert agent_data["name"] == "second-agent"

    def test_new_team_endpoint_available_after_resync(self, test_agent: Agent, test_team: Team, second_team: Team):
        """Test that individual team endpoint is available for teams added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new team
            agent_os.teams.append(second_team)

            # Resync the AgentOS to pick up the new team
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], teams=[test_team], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify the new team's individual endpoint is accessible
            response = client.get(f"/teams/{second_team.id}")
            assert response.status_code == 200
            team_data = response.json()
            assert team_data["id"] == "second-team-id"
            assert team_data["name"] == "second-team"

    def test_new_workflow_endpoint_available_after_resync(
        self, test_agent: Agent, test_workflow: Workflow, second_workflow: Workflow
    ):
        """Test that individual workflow endpoint is available for workflows added during lifespan."""
        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add the new workflow
            agent_os.workflows.append(second_workflow)

            # Resync the AgentOS to pick up the new workflow
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], workflows=[test_workflow], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify lifespan was executed
            assert lifespan_executed is True

            # Verify the new workflow's individual endpoint is accessible
            response = client.get(f"/workflows/{second_workflow.id}")
            assert response.status_code == 200
            workflow_data = response.json()
            assert workflow_data["id"] == "second-workflow-id"
            assert workflow_data["name"] == "second-workflow"


class TestResyncConfig:
    """Tests to verify that resync updates the config endpoint correctly."""

    def test_config_reflects_agents_added_in_lifespan(self, test_agent: Agent, second_agent: Agent):
        """Test that the config endpoint reflects agents added during lifespan."""

        @asynccontextmanager
        async def lifespan(app, agent_os):
            # Add the new agent
            agent_os.agents.append(second_agent)

            # Resync the AgentOS to pick up the new agent
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify config reflects both agents
            response = client.get("/config")
            assert response.status_code == 200
            config = response.json()
            assert len(config["agents"]) == 2

            agent_ids = [agent["id"] for agent in config["agents"]]
            assert "test-agent-id" in agent_ids
            assert "second-agent-id" in agent_ids

    def test_config_reflects_teams_added_in_lifespan(self, test_agent: Agent, test_team: Team, second_team: Team):
        """Test that the config endpoint reflects teams added during lifespan."""

        @asynccontextmanager
        async def lifespan(app, agent_os):
            # Add the new team
            agent_os.teams.append(second_team)

            # Resync the AgentOS to pick up the new team
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], teams=[test_team], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify config reflects both teams
            response = client.get("/config")
            assert response.status_code == 200
            config = response.json()
            assert len(config["teams"]) == 2

            team_ids = [team["id"] for team in config["teams"]]
            assert "test-team-id" in team_ids
            assert "second-team-id" in team_ids

    def test_config_reflects_workflows_added_in_lifespan(
        self, test_agent: Agent, test_workflow: Workflow, second_workflow: Workflow
    ):
        """Test that the config endpoint reflects workflows added during lifespan."""

        @asynccontextmanager
        async def lifespan(app, agent_os):
            # Add the new workflow
            agent_os.workflows.append(second_workflow)

            # Resync the AgentOS to pick up the new workflow
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], workflows=[test_workflow], lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify config reflects both workflows
            response = client.get("/config")
            assert response.status_code == 200
            config = response.json()
            assert len(config["workflows"]) == 2

            workflow_ids = [workflow["id"] for workflow in config["workflows"]]
            assert "test-workflow-id" in workflow_ids
            assert "second-workflow-id" in workflow_ids


class TestResyncMultipleTimes:
    """Tests to verify that resync can be called multiple times."""

    def test_multiple_resync_calls_preserve_endpoints(self, test_agent: Agent):
        """Test that multiple resync calls preserve all endpoints."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Perform multiple resyncs
            for i in range(3):
                agent_os.resync(app=app)

                # Verify home endpoint still works after each resync
                response = client.get("/")
                assert response.status_code == 200, f"Home (/) failed after resync {i + 1}"
                data = response.json()
                assert "name" in data, f"Home (/) missing 'name' after resync {i + 1}"
                assert "AgentOS API" in data["name"], f"Home (/) missing 'AgentOS API' after resync {i + 1}"

                # Verify health endpoint still works after each resync
                response = client.get("/health")
                assert response.status_code == 200, f"Health failed after resync {i + 1}"

                # Verify agents endpoint still works after each resync
                response = client.get("/agents")
                assert response.status_code == 200, f"Agents failed after resync {i + 1}"

    def test_resync_does_not_duplicate_routes(self, test_agent: Agent):
        """Test that resync does not create duplicate routes."""
        agent_os = AgentOS(agents=[test_agent])
        app = agent_os.get_app()

        with TestClient(app):
            # Get route count before multiple resyncs
            routes_before = [route for route in app.routes if hasattr(route, "path")]
            unique_paths_before = set((route.path, tuple(getattr(route, "methods", []))) for route in routes_before)

            # Perform multiple resyncs
            for _ in range(3):
                agent_os.resync(app=app)

            # Get route count after resyncs
            routes_after = [route for route in app.routes if hasattr(route, "path")]
            unique_paths_after = set((route.path, tuple(getattr(route, "methods", []))) for route in routes_after)

            # Verify no duplicate routes were created
            assert len(unique_paths_after) == len(unique_paths_before), "Resync created duplicate routes"


class TestResyncPreservesCustomRoutes:
    """Tests to verify that resync preserves custom routes from base_app."""

    def test_resync_preserves_custom_get_route(self, test_agent: Agent, second_agent: Agent):
        """Test that resync preserves a custom GET route from base_app."""
        from fastapi import FastAPI

        # Create a custom FastAPI app with a custom route
        custom_app = FastAPI()

        @custom_app.get("/status")
        def get_status():
            return {"status": "healthy"}

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify custom route works before resync
            response = client.get("/status")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"

            # Add new agent and resync
            agent_os.agents.append(second_agent)
            agent_os.resync(app=app)

            # Verify custom route still works after resync
            response = client.get("/status")
            assert response.status_code == 200, "Custom route was deleted after resync"
            assert response.json()["status"] == "healthy"

    def test_resync_preserves_custom_post_route(self, test_agent: Agent, second_agent: Agent):
        """Test that resync preserves a custom POST route from base_app."""
        from fastapi import FastAPI

        custom_app = FastAPI()

        @custom_app.post("/custom/data")
        def post_data():
            return {"received": True}

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify custom route works before resync
            response = client.post("/custom/data")
            assert response.status_code == 200

            # Add new agent and resync
            agent_os.agents.append(second_agent)
            agent_os.resync(app=app)

            # Verify custom route still works after resync
            response = client.post("/custom/data")
            assert response.status_code == 200, "Custom POST route was deleted after resync"

    def test_resync_preserves_multiple_custom_routes(self, test_agent: Agent, second_agent: Agent):
        """Test that resync preserves multiple custom routes from base_app."""
        from fastapi import FastAPI

        custom_app = FastAPI()

        @custom_app.get("/status")
        def get_status():
            return {"status": "healthy"}

        @custom_app.get("/custom/endpoint")
        def custom_endpoint():
            return {"message": "custom"}

        @custom_app.post("/custom/data")
        def post_data():
            return {"received": True}

        @custom_app.put("/custom/update")
        def update_data():
            return {"updated": True}

        @custom_app.delete("/custom/delete")
        def delete_data():
            return {"deleted": True}

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify all custom routes work before resync
            status_response = client.get("/status")
            assert status_response.status_code == 200
            custom_endpoint_response = client.get("/custom/endpoint")
            assert custom_endpoint_response.status_code == 200
            post_data_response = client.post("/custom/data")
            assert post_data_response.status_code == 200
            update_data_response = client.put("/custom/update")
            assert update_data_response.status_code == 200
            delete_data_response = client.delete("/custom/delete")
            assert delete_data_response.status_code == 200

            # Add new agent and resync
            agent_os.agents.append(second_agent)
            agent_os.resync(app=app)

            # Verify all custom routes still work after resync
            status_response = client.get("/status")
            assert status_response.status_code == 200, "GET /status was deleted"
            custom_endpoint_response = client.get("/custom/endpoint")
            assert custom_endpoint_response.status_code == 200, "GET /custom/endpoint was deleted"
            post_data_response = client.post("/custom/data")
            assert post_data_response.status_code == 200, "POST /custom/data was deleted"
            update_data_response = client.put("/custom/update")
            assert update_data_response.status_code == 200, "PUT /custom/update was deleted"
            delete_data_response = client.delete("/custom/delete")
            assert delete_data_response.status_code == 200, "DELETE /custom/delete was deleted"

    def test_resync_preserves_custom_routes_after_multiple_resyncs(self, test_agent: Agent):
        """Test that custom routes are preserved after multiple resync calls."""
        from fastapi import FastAPI

        custom_app = FastAPI()

        @custom_app.get("/status")
        def get_status():
            return {"status": "healthy"}

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Perform multiple resyncs
            for i in range(5):
                agent_os.resync(app=app)

                # Verify custom route still works after each resync
                response = client.get("/status")
                assert response.status_code == 200, f"Custom route deleted after resync {i + 1}"

    def test_resync_preserves_custom_routes_and_updates_agents(self, test_agent: Agent, second_agent: Agent):
        """Test that custom routes are preserved AND new agents are picked up after resync."""
        from fastapi import FastAPI

        custom_app = FastAPI()

        @custom_app.get("/status")
        def get_status():
            return {"status": "healthy"}

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app)
        app = agent_os.get_app()

        with TestClient(app) as client:
            # Verify initial state
            response = client.get("/status")
            assert response.status_code == 200

            response = client.get("/agents")
            assert response.status_code == 200
            assert len(response.json()) == 1

            # Add new agent and resync
            agent_os.agents.append(second_agent)
            agent_os.resync(app=app)

            # Verify custom route preserved
            response = client.get("/status")
            assert response.status_code == 200, "Custom route was deleted"

            # Verify new agent was picked up
            response = client.get("/agents")
            assert response.status_code == 200
            assert len(response.json()) == 2, "New agent was not picked up after resync"

    def test_resync_preserves_custom_routes_in_lifespan(self, test_agent: Agent, second_agent: Agent):
        """Test that custom routes are preserved when resync is called in lifespan."""
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        custom_app = FastAPI()

        @custom_app.get("/status")
        def get_status():
            return {"status": "healthy"}

        lifespan_executed = False

        @asynccontextmanager
        async def lifespan(app, agent_os):
            nonlocal lifespan_executed
            lifespan_executed = True

            # Add new agent during lifespan
            agent_os.agents.append(second_agent)
            agent_os.resync(app=app)

            yield

        agent_os = AgentOS(agents=[test_agent], base_app=custom_app, lifespan=lifespan)
        app = agent_os.get_app()

        with TestClient(app) as client:
            assert lifespan_executed is True

            # Verify custom route still works after lifespan resync
            response = client.get("/status")
            assert response.status_code == 200, "Custom route was deleted during lifespan resync"

            # Verify new agent was picked up
            response = client.get("/agents")
            assert response.status_code == 200
            assert len(response.json()) == 2
