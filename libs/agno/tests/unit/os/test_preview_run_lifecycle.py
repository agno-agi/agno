"""Preview runs are version-stable across their lifecycle.

The Studio 3.0 preview contract:
- A run started with an explicit ``version`` form field (draft preview)
  records that version on the run itself (run metadata), so the run is
  self-describing about what it executed.
- Lifecycle routes (continue) read the stamp back and resolve the SAME
  version - a v2 preview that pauses or completes continues as v2 even
  though v1 is the current published version, and even after the draft
  moves on.
- A draft-only component's preview run stays listable and continuable over
  REST: the resolvers forward published_only on the non-factory branch too,
  so lifecycle reads do not 404 on a component with no published version.
- Runs without a stamp (legacy, pre-stamp) keep today's unpinned resolution.
"""

from typing import Any, AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.utils import COMPONENT_VERSION_METADATA_KEY
from agno.registry import Registry
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """Offline model answering with a canned string that names itself.

    Each saved component version carries a different model id, so the
    response content proves WHICH version's config actually executed.
    """

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._resp()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._resp()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._resp()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp()


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "preview_lifecycle.db"))


@pytest.fixture
def model_v1():
    return ScriptedModel("model-v1", "answer from v1")


@pytest.fixture
def model_v2():
    return ScriptedModel("model-v2", "answer from v2")


@pytest.fixture
def registry(db, model_v1, model_v2):
    return Registry(name="preview-registry", dbs=[db], models=[model_v1, model_v2])


@pytest.fixture
def client(db, registry):
    agent_os = AgentOS(db=db, registry=registry, telemetry=False)
    return TestClient(agent_os.get_app(), raise_server_exceptions=False)


def _save_agent_v1_published_v2_draft(db, model_v1, model_v2) -> str:
    """v1 published (current), v2 draft: unpinned resolution answers v1."""
    v1 = Agent(id="pv-agent", name="PV", model=model_v1, instructions="You are v1")
    assert v1.save(db=db, stage="published") == 1
    v2 = Agent(id="pv-agent", name="PV", model=model_v2, instructions="You are v2")
    assert v2.save(db=db, stage="draft") == 2
    return "pv-agent"


def _preview_run(client, agent_id: str, version: int) -> dict:
    response = client.post(
        f"/agents/{agent_id}/runs",
        data={"message": "hi", "stream": "false", "version": str(version)},
    )
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


class TestPreviewRunStampsVersion:
    def test_preview_run_records_pinned_version_on_the_stored_run(self, db, client, model_v1, model_v2):
        agent_id = _save_agent_v1_published_v2_draft(db, model_v1, model_v2)

        body = _preview_run(client, agent_id, version=2)
        assert body["content"] == "answer from v2"
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2

        stored = client.get(f"/agents/{agent_id}/runs/{body['run_id']}", params={"session_id": body["session_id"]})
        assert stored.status_code == 200, (stored.status_code, stored.text)
        assert (stored.json().get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2

    def test_unpinned_run_records_no_stamp(self, db, client, model_v1, model_v2):
        agent_id = _save_agent_v1_published_v2_draft(db, model_v1, model_v2)

        response = client.post(f"/agents/{agent_id}/runs", data={"message": "hi", "stream": "false"})
        assert response.status_code == 200, (response.status_code, response.text)
        body = response.json()
        assert body["content"] == "answer from v1"
        assert COMPONENT_VERSION_METADATA_KEY not in (body.get("metadata") or {})

    def test_team_preview_run_records_pinned_version(self, db, registry, model_v1, model_v2):
        member = Agent(id="member-a", name="Member", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        t1 = Team(id="pv-team", name="PVTeam", model=model_v1, members=[member], instructions="You are v1")
        assert t1.save(db=db, stage="published") == 1
        t2 = Team(id="pv-team", name="PVTeam", model=model_v2, members=[member], instructions="You are v2")
        assert t2.save(db=db, stage="draft") == 2
        client = TestClient(AgentOS(db=db, registry=registry, telemetry=False).get_app(), raise_server_exceptions=False)

        response = client.post("/teams/pv-team/runs", data={"message": "hi", "stream": "false", "version": "2"})
        assert response.status_code == 200, (response.status_code, response.text)
        body = response.json()
        assert body["content"] == "answer from v2"
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2

        cont = client.post(
            f"/teams/pv-team/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, (cont.status_code, cont.text)
        assert cont.json()["content"] == "answer from v2"


class TestContinueResolvesStampedVersion:
    def test_continue_resolves_the_stamped_version_not_current(self, db, client, model_v1, model_v2):
        """A v2 preview run must continue as v2, though v1 is current."""
        agent_id = _save_agent_v1_published_v2_draft(db, model_v1, model_v2)
        body = _preview_run(client, agent_id, version=2)

        cont = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "follow up", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, (cont.status_code, cont.text)
        continued = cont.json()
        assert continued["content"] == "answer from v2"
        # The rebuilt system message proves the loaded component's
        # instructions are v2's, not the published v1's.
        system_messages = [m["content"] for m in continued.get("messages") or [] if m.get("role") == "system"]
        assert system_messages and all(m == "You are v2" for m in system_messages)

    def test_stamp_survives_the_continuation(self, db, client, model_v1, model_v2):
        """The continued run keeps its stamp, so a SECOND continue is stable too."""
        agent_id = _save_agent_v1_published_v2_draft(db, model_v1, model_v2)
        body = _preview_run(client, agent_id, version=2)

        first = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "one", "session_id": body["session_id"], "stream": "false"},
        )
        assert first.status_code == 200, (first.status_code, first.text)
        second = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "two", "session_id": body["session_id"], "stream": "false"},
        )
        assert second.status_code == 200, (second.status_code, second.text)
        assert second.json()["content"] == "answer from v2"


class TestDraftOnlyWorkflowLifecycle:
    def _save_draft_only_workflow(self, db, model_v1) -> str:
        member = Agent(id="wf-member", name="WFMember", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        workflow = Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)])
        assert workflow.save(db=db, stage="draft") == 1
        return "pv-flow"

    def _preview_workflow_run(self, client, workflow_id: str) -> dict:
        response = client.post(
            f"/workflows/{workflow_id}/runs",
            data={"message": "go", "stream": "false", "version": "1"},
        )
        assert response.status_code == 200, (response.status_code, response.text)
        return response.json()

    def test_draft_only_workflow_preview_run_is_listable(self, db, client, model_v1):
        workflow_id = self._save_draft_only_workflow(db, model_v1)
        body = self._preview_workflow_run(client, workflow_id)

        listing = client.get(f"/workflows/{workflow_id}/runs", params={"session_id": body["session_id"]})
        assert listing.status_code == 200, (listing.status_code, listing.text)
        assert [run["run_id"] for run in listing.json()] == [body["run_id"]]

    def test_draft_only_workflow_preview_run_is_continuable_not_404(self, db, client, model_v1):
        """The resolver must reach the draft-only workflow; the only refusal
        left is the run-state one (this run already completed), never the
        'Workflow not found' the published-only default used to produce."""
        workflow_id = self._save_draft_only_workflow(db, model_v1)
        body = self._preview_workflow_run(client, workflow_id)

        cont = client.post(
            f"/workflows/{workflow_id}/runs/{body['run_id']}/continue",
            data={"session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 409, (cont.status_code, cont.text)
        assert cont.json()["detail"] == "run is already completed"

    def test_draft_only_workflow_run_is_pollable(self, db, client, model_v1):
        workflow_id = self._save_draft_only_workflow(db, model_v1)
        body = self._preview_workflow_run(client, workflow_id)

        stored = client.get(
            f"/workflows/{workflow_id}/runs/{body['run_id']}", params={"session_id": body["session_id"]}
        )
        assert stored.status_code == 200, (stored.status_code, stored.text)
        assert stored.json()["status"] == "COMPLETED"

    def test_workflow_preview_run_records_pinned_version(self, db, client, model_v1):
        workflow_id = self._save_draft_only_workflow(db, model_v1)
        body = self._preview_workflow_run(client, workflow_id)

        stored = client.get(
            f"/workflows/{workflow_id}/runs/{body['run_id']}", params={"session_id": body["session_id"]}
        )
        assert stored.status_code == 200, (stored.status_code, stored.text)
        assert (stored.json().get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 1


class TestResolverForwardsPublishedOnly:
    """resolve_agent/team/workflow must forward published_only on the
    NON-factory branch too; the loader default (True) used to make lifecycle
    reads 404 on draft-only components."""

    @pytest.mark.asyncio
    async def test_resolve_agent_reaches_a_draft_only_component(self, db, registry, model_v1):
        from fastapi import HTTPException

        from agno.os.utils import resolve_agent

        Agent(id="draft-agent", name="Draft", model=model_v1, instructions="draft").save(db=db, stage="draft")

        agent = await resolve_agent("draft-agent", None, db, registry, published_only=False)
        assert agent is not None and agent.id == "draft-agent"
        # Dispatch surfaces keep refusing the draft-only component.
        with pytest.raises(HTTPException) as excinfo:
            await resolve_agent("draft-agent", None, db, registry)
        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_team_reaches_a_draft_only_component(self, db, registry, model_v1):
        from fastapi import HTTPException

        from agno.os.utils import resolve_team

        member = Agent(id="draft-team-member", name="M", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        Team(id="draft-team", name="Draft", model=model_v1, members=[member]).save(db=db, stage="draft")

        team = await resolve_team("draft-team", None, db, registry, published_only=False)
        assert team is not None and team.id == "draft-team"
        with pytest.raises(HTTPException) as excinfo:
            await resolve_team("draft-team", None, db, registry)
        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_workflow_reaches_a_draft_only_component(self, db, registry, model_v1):
        from fastapi import HTTPException

        from agno.os.utils import resolve_workflow

        member = Agent(id="draft-flow-member", name="M", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        Workflow(id="draft-flow", name="Draft", steps=[Step(name="s1", agent=member)]).save(db=db, stage="draft")

        workflow = await resolve_workflow("draft-flow", None, db, registry, published_only=False)
        assert workflow is not None and workflow.id == "draft-flow"
        with pytest.raises(HTTPException) as excinfo:
            await resolve_workflow("draft-flow", None, db, registry)
        assert excinfo.value.status_code == 404


class TestLegacyRunsKeepTodayResolution:
    def test_unstamped_run_continues_with_current_resolution(self, db, client, model_v1, model_v2, monkeypatch):
        """A pre-stamp preview run (no version recorded) must keep today's
        behavior: continue resolves the current published version."""
        import agno.os.routers.agents.router as agents_router

        agent_id = _save_agent_v1_published_v2_draft(db, model_v1, model_v2)
        # Simulate a run started before stamping existed.
        monkeypatch.setattr(agents_router, "stamp_component_version", lambda kwargs, version: None)
        body = _preview_run(client, agent_id, version=2)
        assert body["content"] == "answer from v2"
        assert COMPONENT_VERSION_METADATA_KEY not in (body.get("metadata") or {})
        monkeypatch.undo()

        cont = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "follow up", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, (cont.status_code, cont.text)
        # Unpinned resolution: the CURRENT PUBLISHED version (v1). This is
        # the legacy drift the stamp exists to prevent - kept on purpose for
        # runs that carry no stamp.
        assert cont.json()["content"] == "answer from v1"
