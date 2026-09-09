"""Event-stream sync on the continue paths (agents/teams inline streamers,
non-stream JSON paths, and the workflow streamer's run-row status source).

A continue of a formerly-queued/streamed run must not leave the stream view
PAUSED forever: the inline streamers re-register, mark RUNNING, publish the
post-approval events, and complete with the run row's true final status; the
non-stream paths do a status-only sync when the stream already tracks the run.
"""

from typing import Any, List, Optional

import pytest

import agno.os.event_streams as es_mod
from agno.os.event_streams import InMemoryEventStream
from agno.run.base import RunStatus


@pytest.fixture()
def stream():
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    original = es_mod._event_stream
    # Fresh buffer per test: the default wraps the process-global singleton,
    # which would leak run registrations across tests
    fresh = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    es_mod._event_stream = fresh
    yield fresh
    es_mod._event_stream = original


async def _park_paused(stream: InMemoryEventStream, run_id: str, n_events: int = 1) -> None:
    """Simulate the pre-pause history: a streamed run that paused for HITL."""
    from agno.run.team import RunContentEvent

    await stream.register_run(run_id, RunStatus.pending)
    await stream.set_run_status(run_id, RunStatus.running)
    for i in range(n_events):
        await stream.add_event(run_id, RunContentEvent(run_id=run_id, content=f"pre-{i}"))
    await stream.complete_run(run_id, RunStatus.paused)


class _Session:
    def __init__(self, runs: List[Any]):
        self.runs = runs

    def get_run(self, run_id: str):
        return next((r for r in self.runs if getattr(r, "run_id", None) == run_id), None)


class FakeAgent:
    def __init__(self, chunks: List[Any], final_run: Any):
        self.chunks = chunks
        self.final_run = final_run

    def acontinue_run(self, **kwargs: Any):
        return self._stream()

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk

    async def aget_session(self, session_id: Optional[str] = None):
        return _Session([self.final_run])


class TestAgentInlineContinueSync:
    @pytest.mark.asyncio
    async def test_inline_continue_reaches_terminal_and_publishes_events(self, stream):
        """Default (background=false) continue of a formerly-queued run: the
        stream must leave PAUSED, receive the post-approval events, and end
        at the run's true terminal status."""
        from agno.os.routers.agents.router import agent_continue_response_streamer
        from agno.run.agent import RunContentEvent

        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        agent: Any = FakeAgent([RunContentEvent(run_id="r1", content="post-approval")], final_run)

        chunks = [c async for c in agent_continue_response_streamer(agent, run_id="r1", session_id="s1")]

        assert chunks, "streamer must still yield SSE chunks"
        assert await stream.get_run_status("r1") == RunStatus.completed, (
            "the stream must reach the run's terminal status, not stay PAUSED"
        )
        replayed = await stream.replay("r1")
        assert any("post-approval" in str(payload) for _idx, payload in replayed), (
            "post-approval events must be buffered for /resume"
        )

    @pytest.mark.asyncio
    async def test_re_pause_via_continue_says_paused_not_completed(self, stream):
        from agno.os.routers.agents.router import agent_continue_response_streamer
        from agno.run.agent import RunContentEvent

        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.paused})()
        agent: Any = FakeAgent([RunContentEvent(run_id="r1", content="post")], final_run)

        async for _c in agent_continue_response_streamer(agent, run_id="r1", session_id="s1"):
            pass

        assert await stream.get_run_status("r1") == RunStatus.paused, (
            "a continue that re-paused must leave the stream PAUSED, never COMPLETED"
        )

    @pytest.mark.asyncio
    async def test_fork_continue_does_not_touch_original_stream(self, stream):
        """fork=True mints a NEW run_id inside acontinue_run: publishing under
        the original run_id would corrupt the paused original's stream."""
        from agno.os.routers.agents.router import agent_continue_response_streamer
        from agno.run.agent import RunContentEvent

        await _park_paused(stream, "r1", n_events=1)
        before = await stream.replay("r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        agent: Any = FakeAgent([RunContentEvent(run_id="r1-fork", content="forked")], final_run)

        async for _c in agent_continue_response_streamer(agent, run_id="r1", session_id="s1", fork=True):
            pass

        assert await stream.get_run_status("r1") == RunStatus.paused
        assert await stream.replay("r1") == before


class FakeTeam:
    def __init__(self, chunks: List[Any], final_run: Any):
        self.chunks = chunks
        self.final_run = final_run

    def acontinue_run(self, **kwargs: Any):
        return self._stream()

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk

    async def aget_session(self, session_id: Optional[str] = None):
        return _Session([self.final_run])


class TestTeamInlineContinueSync:
    @pytest.mark.asyncio
    async def test_inline_continue_reaches_terminal(self, stream):
        from agno.os.routers.teams.router import team_continue_response_streamer
        from agno.run.team import RunContentEvent

        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        team: Any = FakeTeam([RunContentEvent(run_id="r1", content="post-approval")], final_run)

        async for _c in team_continue_response_streamer(team, run_id="r1", requirements=[], session_id="s1"):
            pass

        assert await stream.get_run_status("r1") == RunStatus.completed
        replayed = await stream.replay("r1")
        assert any("post-approval" in str(payload) for _idx, payload in replayed)

    @pytest.mark.asyncio
    async def test_re_pause_via_continue_says_paused(self, stream):
        from agno.os.routers.teams.router import team_continue_response_streamer
        from agno.run.team import RunContentEvent

        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.paused})()
        team: Any = FakeTeam([RunContentEvent(run_id="r1", content="post")], final_run)

        async for _c in team_continue_response_streamer(team, run_id="r1", requirements=[], session_id="s1"):
            pass

        assert await stream.get_run_status("r1") == RunStatus.paused


class TestTeamForkGate:
    @pytest.mark.asyncio
    async def test_fork_continue_does_not_touch_original_stream(self, stream):
        """Twin of the agent gate: fork/regenerate mint a NEW run_id inside
        acontinue_run - publishing under the original run_id would corrupt
        the paused original's stream. They arrive via **kwargs on the team
        streamer (no typed params)."""
        from agno.os.routers.teams.router import team_continue_response_streamer
        from agno.run.team import RunContentEvent

        await _park_paused(stream, "r1", n_events=1)
        before = await stream.replay("r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        team: Any = FakeTeam([RunContentEvent(run_id="r1-fork", content="forked")], final_run)

        async for _c in team_continue_response_streamer(team, run_id="r1", requirements=[], session_id="s1", fork=True):
            pass

        assert await stream.get_run_status("r1") == RunStatus.paused
        assert await stream.replay("r1") == before


class FakeWorkflow:
    def __init__(self, chunks: List[Any], session_runs: List[Any]):
        self.chunks = chunks
        self.session_runs = session_runs

    async def acontinue_run(self, **kwargs: Any):
        return self._stream()

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk

    async def _apublish_stream_event(self, event: Any, run_id: str, websocket_handler: Any = None):
        await es_mod.get_event_stream().add_event(run_id, event)

    async def aget_session(self, session_id: Optional[str] = None):
        return _Session(self.session_runs)


class TestWorkflowStreamerRunRowSource:
    @pytest.mark.asyncio
    async def test_final_status_comes_from_this_run_not_last_session_row(self, stream):
        """Under interleaving another run appended to the same session is the
        LAST row: session.runs[-1] reported that run's status. The terminal
        write must use get_run(run_id)."""
        from agno.os.routers.workflows.router import workflow_continue_response_streamer
        from agno.run.workflow import WorkflowCompletedEvent

        await _park_paused(stream, "r1")
        continued = type("R", (), {"run_id": "r1", "status": RunStatus.completed, "is_paused": False})()
        interloper = type("R", (), {"run_id": "r2", "status": RunStatus.running, "is_paused": False})()
        workflow: Any = FakeWorkflow(
            [WorkflowCompletedEvent(run_id="r1")],
            [continued, interloper],  # runs[-1] is the OTHER run
        )

        async for _c in workflow_continue_response_streamer(workflow, run_id="r1", session_id="s1"):
            pass

        assert await stream.get_run_status("r1") == RunStatus.completed, (
            "final status must come from get_run(run_id), not session.runs[-1]"
        )


class TestNonStreamStatusOnlySync:
    @pytest.mark.asyncio
    async def test_tracked_paused_run_reaches_terminal(self, stream):
        from agno.os.utils import acomplete_continue_stream

        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        component: Any = FakeAgent([], final_run)

        await acomplete_continue_stream(component, "r1", "s1", only_if_tracked=True)
        assert await stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_untracked_run_is_left_alone(self, stream):
        """A run that never rode the queue or a stream has no stream view;
        the status-only sync must not fabricate one."""
        from agno.os.utils import acomplete_continue_stream

        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        component: Any = FakeAgent([], final_run)

        await acomplete_continue_stream(component, "r1", "s1", only_if_tracked=True)
        assert await stream.get_run_status("r1") is None

    @pytest.mark.asyncio
    async def test_final_status_hint_skips_session_read(self, stream):
        from agno.os.utils import acomplete_continue_stream

        await _park_paused(stream, "r1")

        class NoSession:
            async def aget_session(self, session_id: Optional[str] = None):
                raise AssertionError("must not read the session when a status hint is given")

        await acomplete_continue_stream(NoSession(), "r1", "s1", only_if_tracked=True, final_status=RunStatus.paused)
        assert await stream.get_run_status("r1") == RunStatus.paused


class TestInlineContinueSettlesTicket:
    """B2: the inline (background=false, default) continue of a DURABLE
    paused run must terminalize its queue ticket - paused tickets are
    retention-exempt, so a leaked one says paused forever and accumulates."""

    @staticmethod
    async def _paused_ticket_worker(run_id: str = "r1"):
        from types import SimpleNamespace

        from agno.db.schemas.jobs import QueuedJob
        from agno.job_queue.store import InMemoryQueueStore

        store = InMemoryQueueStore()
        await store.enqueue_job(
            QueuedJob(
                id=run_id,
                component_type="agent",
                component_id="a1",
                session_id="s1",
                payload={"input": "hi"},
                max_attempts=1,
            ).to_dict()
        )
        claimed = await store.claim_job("w1")
        assert await store.complete_job(run_id, "w1", claimed["attempt"], "paused")
        return SimpleNamespace(store=store), store

    @pytest.mark.asyncio
    async def test_inline_stream_continue_terminalizes_ticket(self, stream):
        from agno.os.routers.agents.router import agent_continue_response_streamer
        from agno.run.agent import RunContentEvent

        worker, store = await self._paused_ticket_worker()
        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.completed})()
        agent: Any = FakeAgent([RunContentEvent(run_id="r1", content="post")], final_run)

        async for _c in agent_continue_response_streamer(agent, run_id="r1", session_id="s1", queue_worker=worker):
            pass

        job = await store.get_job("r1")
        assert job["status"] == "completed", "the durable ticket must not stay paused after an inline continue"

    @pytest.mark.asyncio
    async def test_inline_re_pause_leaves_ticket_paused(self, stream):
        from agno.os.routers.agents.router import agent_continue_response_streamer
        from agno.run.agent import RunContentEvent

        worker, store = await self._paused_ticket_worker()
        await _park_paused(stream, "r1")
        final_run = type("R", (), {"run_id": "r1", "status": RunStatus.paused})()
        agent: Any = FakeAgent([RunContentEvent(run_id="r1", content="post")], final_run)

        async for _c in agent_continue_response_streamer(agent, run_id="r1", session_id="s1", queue_worker=worker):
            pass

        assert (await store.get_job("r1"))["status"] == "paused", "a re-paused continue keeps the ticket continuable"

    @pytest.mark.asyncio
    async def test_settle_maps_error_to_failed_with_reason(self):
        from agno.os.job_queue import asettle_paused_ticket

        worker, store = await self._paused_ticket_worker()
        await asettle_paused_ticket(worker, "r1", RunStatus.error)
        job = await store.get_job("r1")
        assert job["status"] == "failed"
        assert "inline continue" in job["error"]

    @pytest.mark.asyncio
    async def test_settle_without_worker_or_ticket_is_a_noop(self):
        from agno.os.job_queue import asettle_paused_ticket

        await asettle_paused_ticket(None, "r1", RunStatus.completed)  # no worker: must not raise
        worker, store = await self._paused_ticket_worker("other")
        await asettle_paused_ticket(worker, "never-queued", RunStatus.completed)  # no ticket: no-op
        assert (await store.get_job("other"))["status"] == "paused"
