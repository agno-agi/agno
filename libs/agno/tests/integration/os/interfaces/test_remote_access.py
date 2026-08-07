import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent, RemoteAgent
from agno.os.app import AgentOS
from agno.os.interfaces.remote_access import RemoteAccess
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.utils.http import set_default_async_client


@pytest.fixture
def exposed_agent():
    agent = Agent(id="exposed-agent", name="Exposed Agent", instructions="You are a helpful assistant.")
    # Return same instance from deep_copy so arun patches work
    agent.deep_copy = lambda **kwargs: agent
    return agent


@pytest.fixture
def internal_agent():
    return Agent(id="internal-agent", name="Internal Agent")


@pytest.fixture
def exposed_team(exposed_agent: Agent):
    team = Team(id="exposed-team", name="Exposed Team", members=[exposed_agent])
    team.deep_copy = lambda **kwargs: team
    return team


@pytest.fixture
def agent_os(exposed_agent: Agent, internal_agent: Agent, exposed_team: Team):
    return AgentOS(
        id="remote-access-test-os",
        agents=[exposed_agent, internal_agent],
        teams=[exposed_team],
        interfaces=[RemoteAccess(agents=[exposed_agent], teams=[exposed_team])],
        telemetry=False,
    )


@pytest.fixture
def test_client(agent_os: AgentOS):
    return TestClient(agent_os.get_app())


def test_remote_access_requires_entities():
    with pytest.raises(ValueError):
        RemoteAccess()


def test_remote_access_workflows_param_logs_error(exposed_agent: Agent):
    """Passing workflows to RemoteAccess logs an error and is ignored."""
    with patch("agno.os.interfaces.remote_access.remote_access.log_error") as mock_log_error:
        interface = RemoteAccess(agents=[exposed_agent], workflows=["anything"])

    mock_log_error.assert_called_once()
    assert "Remote workflows are not a thing" in mock_log_error.call_args.args[0]
    assert not hasattr(interface, "workflows")


def test_remote_access_routes_mounted(agent_os: AgentOS, test_client: TestClient):
    paths = [route.path for route in agent_os.get_routes() if hasattr(route, "path")]

    assert "/remote/config" in paths
    assert "/remote/agents" in paths
    assert "/remote/agents/{agent_id}" in paths
    assert "/remote/agents/{agent_id}/runs" in paths
    assert "/remote/agents/{agent_id}/runs/{run_id}/continue" in paths
    assert "/remote/agents/{agent_id}/runs/{run_id}/cancel" in paths
    assert "/remote/teams/{team_id}/runs" in paths

    # No workflow routes: remote workflows are not a thing
    assert not any(path.startswith("/remote/workflows") for path in paths)

    # Default routes are unaffected
    assert "/agents/{agent_id}/runs" in paths


def test_config_lists_remote_access_interface(test_client: TestClient):
    response = test_client.get("/config")

    assert response.status_code == 200
    interfaces = response.json()["interfaces"]
    assert {"type": "remote_access", "version": "1.0", "route": "/remote"} in interfaces


def test_remote_config_route(test_client: TestClient):
    response = test_client.get("/remote/config")

    assert response.status_code == 200
    data = response.json()
    assert data["os_id"] == "remote"
    assert [agent["id"] for agent in data["agents"]] == ["exposed-agent"]


def test_list_returns_only_opted_in_agents(test_client: TestClient):
    response = test_client.get("/remote/agents")

    assert response.status_code == 200
    assert [agent["id"] for agent in response.json()] == ["exposed-agent"]


def test_non_opted_agent_is_not_reachable(test_client: TestClient):
    response = test_client.get("/remote/agents/internal-agent")
    assert response.status_code == 404

    response = test_client.post("/remote/agents/internal-agent/runs", data={"message": "hi", "stream": "false"})
    assert response.status_code == 404

    # The same agent is still reachable through the default API
    response = test_client.get("/agents/internal-agent")
    assert response.status_code == 200


def test_remote_access_flag_mounts_interface(exposed_agent: Agent, exposed_team: Team):
    """AgentOS(remote_access=True) exposes all local agents and teams at /remote."""
    agent_os = AgentOS(
        id="remote-access-flag-os",
        agents=[exposed_agent],
        teams=[exposed_team],
        remote_access=True,
        telemetry=False,
    )
    app = agent_os.get_app()

    assert any(isinstance(interface, RemoteAccess) for interface in agent_os.interfaces)
    client = TestClient(app)
    assert [a["id"] for a in client.get("/remote/agents").json()] == ["exposed-agent"]
    assert [t["id"] for t in client.get("/remote/teams").json()] == ["exposed-team"]


def test_remote_access_flag_explicit_interface_takes_precedence(exposed_agent: Agent, internal_agent: Agent):
    """An explicit RemoteAccess(...) in interfaces wins over the flag."""
    internal_agent.deep_copy = lambda **kwargs: internal_agent
    agent_os = AgentOS(
        id="remote-access-precedence-os",
        agents=[exposed_agent, internal_agent],
        remote_access=True,
        interfaces=[RemoteAccess(agents=[exposed_agent])],
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())

    assert [a["id"] for a in client.get("/remote/agents").json()] == ["exposed-agent"]
    assert client.get("/remote/agents/internal-agent").status_code == 404


def test_remote_access_flag_excludes_remote_proxies():
    """The flag only exposes local entities: an OS of proxies mounts nothing at /remote."""
    agent_os = AgentOS(
        id="remote-access-proxy-os",
        agents=[RemoteAgent(base_url="http://localhost:59999", agent_id="proxied-agent")],
        remote_access=True,
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())

    assert not any(isinstance(interface, RemoteAccess) for interface in agent_os.interfaces)
    assert client.get("/remote/agents").status_code == 404


def test_agents_only_interface_has_no_team_routes(exposed_agent: Agent):
    agent_os = AgentOS(
        id="agents-only-os",
        agents=[exposed_agent],
        interfaces=[RemoteAccess(agents=[exposed_agent])],
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())

    assert client.get("/remote/agents").status_code == 200
    assert client.get("/remote/teams").status_code == 404
    assert client.get("/remote/workflows").status_code == 404


def test_agent_run_non_streaming(exposed_agent: Agent, test_client: TestClient):
    mock_output = RunOutput(
        run_id="run-1",
        session_id="session-1",
        agent_id=exposed_agent.id,
        content="Hello from the remote agent",
        status=RunStatus.completed,
    )

    with patch.object(exposed_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        response = test_client.post(
            "/remote/agents/exposed-agent/runs",
            data={"message": "hi", "stream": "false", "session_id": "session-1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run-1"
    assert data["content"] == "Hello from the remote agent"
    assert mock_arun.call_args.kwargs["session_id"] == "session-1"


def test_agent_run_streaming(exposed_agent: Agent, test_client: TestClient):
    async def fake_stream(**kwargs):
        yield RunContentEvent(content="Hello ", run_id="run-1")
        yield RunCompletedEvent(content="Hello world", run_id="run-1")

    def fake_arun(**kwargs):
        assert kwargs["stream"] is True
        return fake_stream()

    with patch.object(exposed_agent, "arun", side_effect=fake_arun):
        response = test_client.post(
            "/remote/agents/exposed-agent/runs",
            data={"message": "hi", "stream": "true"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    events = [json.loads(payload)["event"] for payload in payloads]
    assert "RunContent" in events
    assert "RunCompleted" in events


def test_agent_continue_run(exposed_agent: Agent, test_client: TestClient):
    mock_output = RunOutput(
        run_id="run-1",
        session_id="session-1",
        agent_id=exposed_agent.id,
        content="Continued",
        status=RunStatus.completed,
    )

    tools = json.dumps([{"tool_call_id": "tc-1", "tool_name": "my_tool", "result": "42"}])

    with patch.object(exposed_agent, "acontinue_run", new_callable=AsyncMock) as mock_continue:
        mock_continue.return_value = mock_output

        response = test_client.post(
            "/remote/agents/exposed-agent/runs/run-1/continue",
            data={"tools": tools, "stream": "false", "session_id": "session-1"},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Continued"
    updated_tools = mock_continue.call_args.kwargs["updated_tools"]
    assert len(updated_tools) == 1
    assert updated_tools[0].tool_call_id == "tc-1"


def test_agent_cancel_run(exposed_agent: Agent, test_client: TestClient):
    with patch.object(exposed_agent, "acancel_run", new_callable=AsyncMock) as mock_cancel:
        mock_cancel.return_value = True

        response = test_client.post("/remote/agents/exposed-agent/runs/run-1/cancel")

    assert response.status_code == 200
    assert response.json() == {}
    mock_cancel.assert_called_once_with(run_id="run-1")


def test_team_run_non_streaming(exposed_team: Team, test_client: TestClient):
    mock_output = TeamRunOutput(
        run_id="team-run-1",
        session_id="session-1",
        team_id=exposed_team.id,
        content="Hello from the remote team",
        status=RunStatus.completed,
    )

    with patch.object(exposed_team, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        response = test_client.post(
            "/remote/teams/exposed-team/runs",
            data={"message": "hi", "stream": "false"},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Hello from the remote team"


def test_scope_mappings_cover_mounted_families():
    from agno.os.interfaces.remote_access.scopes import get_remote_access_scope_mappings

    mappings = get_remote_access_scope_mappings("/remote")
    assert mappings["POST /remote/agents/*/runs"] == ["agents:run"]
    assert mappings["GET /remote/agents"] == ["agents:read"]
    assert mappings["POST /remote/teams/*/runs/*/continue"] == ["teams:run"]
    assert not any("workflows" in key for key in mappings)

    agents_only = get_remote_access_scope_mappings("/remote", include_teams=False)
    assert all(key.split(" ")[1].startswith("/remote/agents") for key in agents_only)


def test_scopes_resource_extraction_handles_remote_prefix():
    from agno.os.scopes import get_resource_context_from_path

    assert get_resource_context_from_path("/remote/agents/my-agent/runs") == ("agents", "my-agent")
    assert get_resource_context_from_path("/remote/teams/my-team") == ("teams", "my-team")


@pytest.mark.asyncio
async def test_remote_agent_end_to_end(agent_os: AgentOS, exposed_agent: Agent):
    """RemoteAgent talks to the RemoteAccess interface over an in-memory ASGI transport."""
    app = agent_os.get_app()
    transport = httpx.ASGITransport(app=app)
    set_default_async_client(httpx.AsyncClient(transport=transport))

    try:
        remote_agent = RemoteAgent(base_url="http://testserver", agent_id="exposed-agent")

        # Metadata via the interface
        config = await remote_agent.get_agent_config()
        assert config.id == "exposed-agent"
        assert config.name == "Exposed Agent"

        # Non-streaming run via the interface
        mock_output = RunOutput(
            run_id="run-e2e",
            session_id="session-e2e",
            agent_id=exposed_agent.id,
            content="End to end response",
            status=RunStatus.completed,
        )
        with patch.object(exposed_agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = mock_output
            run_output = await remote_agent.arun("hi", session_id="session-e2e", user_id="user-1")

        assert isinstance(run_output, RunOutput)
        assert run_output.content == "End to end response"

        # Non-opted agent is not remotely callable
        hidden_agent = RemoteAgent(base_url="http://testserver", agent_id="internal-agent")
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await hidden_agent.arun("hi")
        assert exc_info.value.response.status_code == 404
    finally:
        set_default_async_client(httpx.AsyncClient())


@pytest.mark.asyncio
async def test_remote_agent_end_to_end_streaming(agent_os: AgentOS, exposed_agent: Agent):
    app = agent_os.get_app()
    transport = httpx.ASGITransport(app=app)
    set_default_async_client(httpx.AsyncClient(transport=transport))

    try:
        remote_agent = RemoteAgent(base_url="http://testserver", agent_id="exposed-agent")

        async def fake_stream(**kwargs):
            yield RunContentEvent(content="Hello ", run_id="run-e2e")
            yield RunCompletedEvent(content="Hello world", run_id="run-e2e")

        def fake_arun(**kwargs):
            return fake_stream()

        with patch.object(exposed_agent, "arun", side_effect=fake_arun):
            events = [event async for event in remote_agent.arun("hi", stream=True, stream_events=True)]

        event_types = [type(event).__name__ for event in events]
        assert "RunContentEvent" in event_types
        assert "RunCompletedEvent" in event_types
    finally:
        set_default_async_client(httpx.AsyncClient())
