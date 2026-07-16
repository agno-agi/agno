from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.team import Team
from agno.utils.component_versioning import pin_component_version_metadata
from agno.workflow import Workflow


class _FakeEntity:
    def __init__(self, entity_id: str, version: int, paused_run):
        self.id = entity_id
        self.name = entity_id
        self._version = version
        self._paused_run = paused_run
        self.store_member_responses = False
        self.continued = False

    async def aget_run_output(self, **kwargs):
        return self._paused_run

    async def acontinue_run(self, **kwargs):
        self.continued = True
        payload = {
            "run_id": kwargs["run_id"],
            "session_id": kwargs.get("session_id"),
            "status": RunStatus.completed,
            "metadata": self._paused_run.metadata,
        }
        for field in ("agent_id", "team_id", "workflow_id"):
            value = getattr(self._paused_run, field, None)
            if value is not None:
                payload[field] = value
        return self._paused_run.__class__(**payload)


def test_agent_continue_reloads_pinned_version(monkeypatch):
    from agno.os.routers.agents import router as agent_router

    paused = RunOutput(
        run_id="run-1",
        session_id="sess-1",
        status=RunStatus.paused,
        agent_id="agent-1",
        metadata=pin_component_version_metadata(None, component_type="agent", component_id="agent-1", version=1),
    )
    current = _FakeEntity("agent-1", 2, paused)
    pinned = _FakeEntity("agent-1", 1, paused)
    resolved_versions = []

    monkeypatch.setattr(agent_router, "get_agent_by_id", lambda **kwargs: current)

    async def _resolve_agent(*args, version=None, **kwargs):
        resolved_versions.append(version)
        return pinned

    monkeypatch.setattr(agent_router, "resolve_agent", _resolve_agent)

    response = TestClient(AgentOS(agents=[Agent(id="placeholder-agent")]).get_app()).post(
        "/agents/agent-1/runs/run-1/continue", data={"session_id": "sess-1", "stream": "false"}
    )

    assert response.status_code == 200
    assert resolved_versions == [1]
    assert pinned.continued is True


def test_team_continue_reloads_pinned_version(monkeypatch):
    from agno.os.routers.teams import router as team_router

    paused = TeamRunOutput(
        run_id="run-1",
        session_id="sess-1",
        status=RunStatus.paused,
        team_id="team-1",
        metadata=pin_component_version_metadata(None, component_type="team", component_id="team-1", version=1),
    )
    current = _FakeEntity("team-1", 2, paused)
    pinned = _FakeEntity("team-1", 1, paused)
    resolved_versions = []

    monkeypatch.setattr(team_router, "get_team_by_id", lambda **kwargs: current)

    async def _resolve_team(*args, version=None, **kwargs):
        resolved_versions.append(version)
        return pinned

    monkeypatch.setattr(team_router, "resolve_team", _resolve_team)

    response = TestClient(AgentOS(teams=[Team(id="placeholder-team", members=[])]).get_app()).post(
        "/teams/team-1/runs/run-1/continue", data={"session_id": "sess-1", "stream": "false"}
    )

    assert response.status_code == 200
    assert resolved_versions == [1]
    assert pinned.continued is True


def test_agent_continue_allows_missing_persisted_run_for_backward_compat(monkeypatch):
    from agno.os.routers.agents import router as agent_router

    paused = RunOutput(
        run_id="run-1",
        session_id="sess-1",
        status=RunStatus.paused,
        agent_id="agent-1",
        metadata=pin_component_version_metadata(None, component_type="agent", component_id="agent-1", version=1),
    )
    current = _FakeEntity("agent-1", 2, paused)
    current.aget_run_output = AsyncMock(return_value=None)

    monkeypatch.setattr(agent_router, "get_agent_by_id", lambda **kwargs: current)

    response = TestClient(AgentOS(agents=[Agent(id="placeholder-agent")]).get_app()).post(
        "/agents/agent-1/runs/run-1/continue", data={"session_id": "sess-1", "stream": "false"}
    )

    assert response.status_code == 200
    assert current.continued is True


def test_workflow_continue_reloads_pinned_version(monkeypatch):
    from agno.os.routers.workflows import router as workflow_router

    paused = WorkflowRunOutput(
        run_id="run-1",
        session_id="sess-1",
        status=RunStatus.paused,
        workflow_id="workflow-1",
        metadata=pin_component_version_metadata(None, component_type="workflow", component_id="workflow-1", version=1),
    )
    current = _FakeEntity("workflow-1", 2, paused)
    pinned = _FakeEntity("workflow-1", 1, paused)
    resolved_versions = []

    async def _resolve_workflow(*args, version=None, **kwargs):
        resolved_versions.append(version)
        return current if version is None else pinned

    monkeypatch.setattr(workflow_router, "resolve_workflow", _resolve_workflow)

    response = TestClient(AgentOS(workflows=[Workflow(id="placeholder-workflow")]).get_app()).post(
        "/workflows/workflow-1/runs/run-1/continue", data={"session_id": "sess-1", "stream": "false"}
    )

    assert response.status_code == 200
    assert resolved_versions == [None, 1]
    assert pinned.continued is True
