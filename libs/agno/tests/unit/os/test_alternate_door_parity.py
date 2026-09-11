"""Door parity for the non-REST surfaces (MCP tools, AG-UI, Slack, A2A).

The REST continue/cancel routes carry two obligations the alternate doors
were missing:

- continue: a status-only event-stream sync once the continue settles. A
  stream-PAUSED run continued through one of these doors otherwise completes
  in the DB while its stream view stays PAUSED - and on Redis the pausing
  replica's TTL refresher keeps those keys alive indefinitely, so every later
  /resume replays the stale paused snapshot forever.
- cancel: tombstone a still-queued durable ticket BEFORE registering the
  cancellation intent. Intent alone does not stop a job no task is executing
  yet: a worker claims the waiting ticket, starts the leg, and the leg only
  dies at its first cancellation checkpoint - burning an attempt and stamping
  a spurious execution start.
"""

import json
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

import agno.os.event_streams as es_mod
import agno.os.job_queue as jq
from agno.os.event_streams import InMemoryEventStream
from agno.run.base import RunStatus


@pytest.fixture()
def stream():
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    original = es_mod._event_stream
    fresh = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    es_mod._event_stream = fresh
    yield fresh
    es_mod._event_stream = original


@pytest.fixture(autouse=True)
def no_active_worker():
    """The doors' ticket-admission gate must see no worker unless a test
    installs one; always restore."""
    original = jq.get_active_queue_worker()
    jq.set_active_queue_worker(None)
    yield
    jq.set_active_queue_worker(original)


async def _park_paused(stream: InMemoryEventStream, run_id: str) -> None:
    """Simulate the pre-pause history: a streamed run that paused for HITL."""
    await stream.register_run(run_id, RunStatus.pending)
    await stream.set_run_status(run_id, RunStatus.running)
    await stream.complete_run(run_id, RunStatus.paused)


class _Session:
    def __init__(self, runs: List[Any]):
        self.runs = runs

    def get_run(self, run_id: str):
        return next((r for r in self.runs if getattr(r, "run_id", None) == run_id), None)


class TestMcpContinueDoorSyncsStream:
    @pytest.mark.asyncio
    async def test_tracked_paused_stream_reaches_final_status(self, stream):
        from agno.os.services.runs import continue_paused_run

        await _park_paused(stream, "r-mcp")

        class FakeAgent:
            id = "a1"

            async def acontinue_run(self, **kwargs):
                return SimpleNamespace(status=RunStatus.completed, run_id="r-mcp")

        result = await continue_paused_run(FakeAgent(), run_id="r-mcp", session_id="s1")

        assert result.status == RunStatus.completed
        assert await stream.get_run_status("r-mcp") == RunStatus.completed, (
            "the MCP continue door must sync a tracked stream off PAUSED"
        )

    @pytest.mark.asyncio
    async def test_never_streamed_run_gets_no_fabricated_stream(self, stream):
        from agno.os.services.runs import continue_paused_run

        class FakeAgent:
            id = "a1"

            async def acontinue_run(self, **kwargs):
                return SimpleNamespace(status=RunStatus.completed, run_id="r-inline")

        await continue_paused_run(FakeAgent(), run_id="r-inline", session_id="s1")

        assert await stream.get_run_status("r-inline") is None, (
            "only_if_tracked: a run that never streamed needs no stream view"
        )


class TestMcpCancelDoorTombstonesTicket:
    @pytest.mark.asyncio
    async def test_ticket_tombstoned_before_intent(self):
        from agno.os.services.runs import cancel_component_run

        order: List[Any] = []

        class FakeWorker:
            async def acancel_queued(self, run_id):
                order.append(("tombstone", run_id))
                return True

        class FakeComponent:
            async def acancel_run(self, run_id):
                order.append(("intent", run_id))
                return True

        jq.set_active_queue_worker(FakeWorker())
        await cancel_component_run(FakeComponent(), "r-c1")

        assert order == [("tombstone", "r-c1"), ("intent", "r-c1")], (
            "a queued durable ticket must be tombstoned before the intent - "
            "intent alone does not stop a job no task is executing yet"
        )

    @pytest.mark.asyncio
    async def test_no_worker_still_cancels(self):
        from agno.os.services.runs import cancel_component_run

        calls: List[str] = []

        class FakeComponent:
            async def acancel_run(self, run_id):
                calls.append(run_id)
                return True

        await cancel_component_run(FakeComponent(), "r-c2")
        assert calls == ["r-c2"]


class TestA2ACancelDelegatesToService:
    """The A2A tasks:cancel handlers must route through the shared cancel
    service (which owns the ticket tombstone), not call acancel_run direct."""

    @staticmethod
    def _build_client(monkeypatch, recorded: List[Any]):
        pytest.importorskip("a2a", reason="a2a-sdk not installed")
        from fastapi import FastAPI
        from fastapi.routing import APIRouter
        from fastapi.testclient import TestClient

        from agno.agent import Agent
        from agno.os.interfaces.a2a.router import attach_routes
        from agno.team import Team

        async def recording_cancel(component, run_id):
            recorded.append((component, run_id))

        monkeypatch.setattr("agno.os.services.runs.cancel_component_run", recording_cancel)

        agent = Agent(id="a2a-agent", name="A2A Agent")
        team = Team(id="a2a-team", name="A2A Team", members=[agent])
        app = FastAPI()
        app.include_router(attach_routes(APIRouter(), agents=[agent], teams=[team]))
        return TestClient(app)

    def test_agent_cancel_routes_through_service(self, monkeypatch):
        recorded: List[Any] = []
        client = self._build_client(monkeypatch, recorded)

        resp = client.post(
            "/agents/a2a-agent/v1/tasks:cancel",
            json={"id": "req-1", "params": {"id": "run-42", "contextId": "ctx-1"}},
        )

        assert resp.status_code == 200
        assert [(getattr(c, "id", None), r) for c, r in recorded] == [("a2a-agent", "run-42")]

    def test_team_cancel_routes_through_service(self, monkeypatch):
        recorded: List[Any] = []
        client = self._build_client(monkeypatch, recorded)

        resp = client.post(
            "/teams/a2a-team/v1/tasks:cancel",
            json={"id": "req-2", "params": {"id": "run-43", "contextId": "ctx-2"}},
        )

        assert resp.status_code == 200
        assert [(getattr(c, "id", None), r) for c, r in recorded] == [("a2a-team", "run-43")]


class TestAguiResumeSyncsStream:
    @pytest.mark.asyncio
    async def test_stream_synced_after_consumption(self, stream, monkeypatch):
        pytest.importorskip("ag_ui", reason="ag_ui not installed")
        from ag_ui.core.types import ToolMessage as AGUIToolMessage

        from agno.agent import Agent
        from agno.models.response import ToolExecution
        from agno.os.interfaces.agui.resume import resume_paused_run
        from agno.run.agent import RunOutput
        from agno.run.base import RunContext
        from agno.run.requirement import RunRequirement
        from agno.session.agent import AgentSession

        await _park_paused(stream, "r-agui")

        requirement = RunRequirement(
            tool_execution=ToolExecution(tool_call_id="tc-1", tool_name="t", requires_confirmation=True)
        )
        paused_run = RunOutput(
            run_id="r-agui", session_id="s-agui", status=RunStatus.paused, requirements=[requirement]
        )
        session = AgentSession(session_id="s-agui", runs=[paused_run])

        agent = Agent(id="agui-agent", name="AGUI Agent")
        agent.db = object()  # resume only checks truthiness

        async def fake_aget_session(session_id: Optional[str] = None):
            return session

        def fake_acontinue_run(**kwargs):
            async def _gen():
                # The run row settles as the continue executes: the post-run
                # session read must see the final status.
                paused_run.status = RunStatus.completed
                yield SimpleNamespace(content="post-approval")

            return _gen()

        monkeypatch.setattr(agent, "aget_session", fake_aget_session)
        monkeypatch.setattr(agent, "acontinue_run", fake_acontinue_run)

        response_stream = await resume_paused_run(
            entity=agent,
            session_id="s-agui",
            tool_messages=[
                AGUIToolMessage(id="m1", role="tool", content=json.dumps({"accepted": True}), tool_call_id="tc-1")
            ],
            run_context=RunContext(run_id="r-agui", session_id="s-agui"),
            run_kwargs={},
        )
        chunks = [c async for c in response_stream]

        assert chunks, "the wrapped stream must still yield the continue's chunks"
        assert await stream.get_run_status("r-agui") == RunStatus.completed, (
            "the AG-UI resume door must sync a tracked stream off PAUSED after consumption"
        )


class TestSlackContinueDoorSyncsStream:
    @pytest.mark.asyncio
    async def test_stream_synced_after_continuation(self, stream):
        pytest.importorskip("slack_sdk", reason="slack_sdk not installed")
        from agno.os.interfaces.slack.hitl import HITLHandler

        await _park_paused(stream, "r-slack")

        final_run = SimpleNamespace(run_id="r-slack", status=RunStatus.completed)

        class FakeEntity:
            id = "slack-agent"

            def acontinue_run(self, **kwargs):
                async def _gen():
                    if False:  # pragma: no cover - empty continue stream
                        yield None

                return _gen()

            async def aget_session(self, session_id: Optional[str] = None):
                return _Session([final_run])

        handler = HITLHandler.__new__(HITLHandler)
        handler.entity = FakeEntity()
        handler.entity_name = "Slack Agent"
        handler.entity_type = "agent"

        ctx = SimpleNamespace(run_id="r-slack", channel="C1", thread_ts=None, msg_ts=None)

        async def _append(**kwargs):
            return None

        await handler.stream_resumed_run(
            ctx, SimpleNamespace(append=_append), requirements=[], session_id="s-slack", user_id=None
        )

        assert await stream.get_run_status("r-slack") == RunStatus.completed, (
            "the Slack continue door must sync a tracked stream off PAUSED"
        )
