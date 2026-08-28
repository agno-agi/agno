"""Workflow event-stream integration: producers publish through the pluggable
event stream (not the legacy in-process singletons), the router reads through
it, and the queue worker can execute streaming workflow jobs.

These are the seams that make workflow background streams observable and
resumable from any replica.
"""

import asyncio
from typing import Any, Optional

import pytest

import agno.os.event_streams as es_mod
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.base import RunStatus
from agno.workflow.workflow import Workflow


@pytest.fixture
def fresh_stream():
    """Install a fresh InMemoryEventStream; restore the original after."""
    original = es_mod._event_stream
    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    set_event_stream(stream)
    yield stream
    es_mod._event_stream = original


class FakeEvent:
    def __init__(self, content: str, run_id: str = "wr1", workflow_run_id: Optional[str] = None):
        self.event = "WorkflowStepContent"
        self.content = content
        self.run_id = run_id
        if workflow_run_id is not None:
            self.workflow_run_id = workflow_run_id

    def to_dict(self):
        return {"event": self.event, "content": self.content, "run_id": self.run_id}


class TestPublishStreamEvent:
    @pytest.mark.asyncio
    async def test_publishes_under_workflow_run_id_and_returns_index(self, fresh_stream):
        wf = Workflow(id="wf-1", name="wf", db=None)
        await fresh_stream.register_run("wr1", RunStatus.running)

        idx0 = await wf._apublish_stream_event(FakeEvent("a"), "wr1")
        idx1 = await wf._apublish_stream_event(FakeEvent("b", workflow_run_id="wr1"), "wr1")

        assert (idx0, idx1) == (0, 1)
        assert await fresh_stream.get_event_count("wr1") == 2

    @pytest.mark.asyncio
    async def test_publish_failure_never_raises(self, fresh_stream):
        wf = Workflow(id="wf-1", name="wf", db=None)

        async def boom(*a, **k):
            raise RuntimeError("redis down")

        fresh_stream.add_event = boom  # type: ignore[method-assign]
        idx = await wf._apublish_stream_event(FakeEvent("a"), "wr1")
        assert idx is None

    @pytest.mark.asyncio
    async def test_websocket_handler_receives_event_with_index(self, fresh_stream):
        wf = Workflow(id="wf-1", name="wf", db=None)
        await fresh_stream.register_run("wr1", RunStatus.running)

        received: list = []

        class Handler:
            async def handle_event(self, event: Any, event_index: Optional[int] = None, run_id: Optional[str] = None):
                received.append((event_index, run_id, event.content))

        await wf._apublish_stream_event(FakeEvent("a"), "wr1", websocket_handler=Handler())
        await asyncio.sleep(0.05)  # handler delivery is fire-and-forget
        assert received == [(0, "wr1", "a")]


class TestHandleEventIsTransportFree:
    @pytest.mark.asyncio
    async def test_handle_event_no_longer_touches_buffer(self, fresh_stream):
        """_handle_event shapes and stores; transport belongs to producers."""
        from agno.run.workflow import WorkflowRunOutput

        wf = Workflow(id="wf-1", name="wf", db=None, store_events=True)
        run_output = WorkflowRunOutput(run_id="wr1", workflow_id="wf-1")
        event = FakeEvent("a")

        result = wf._handle_event(event, run_output)  # type: ignore[arg-type]
        assert result is event
        # Nothing published: the event stream never saw this run
        assert await fresh_stream.get_run_status("wr1") is None


class TestStreamPayloadToDict:
    def test_structured_event(self):
        from agno.os.routers.workflows.router import _stream_payload_to_dict

        d = _stream_payload_to_dict(FakeEvent("a"), 3, "wr1")
        assert d["event_index"] == 3 and d["content"] == "a" and d["run_id"] == "wr1"

    def test_sse_string_payload(self):
        from agno.os.routers.workflows.router import _stream_payload_to_dict

        sse = 'event: WorkflowStepContent\ndata: {"event": "WorkflowStepContent", "content": "a", "event_index": 7, "run_id": "wr1"}\n\n'
        d = _stream_payload_to_dict(sse, 7, "wr1")
        assert d["event_index"] == 7 and d["content"] == "a" and d["run_id"] == "wr1"

    def test_malformed_sse_string_degrades(self):
        from agno.os.routers.workflows.router import _stream_payload_to_dict

        d = _stream_payload_to_dict("data: not-json\n\n", 1, "wr1")
        assert d["event"] == "unknown" and d["event_index"] == 1


class TestWorkerStreamingWorkflowJob:
    @pytest.mark.asyncio
    async def test_streaming_workflow_job_publishes_and_completes(self, fresh_stream):
        """The worker executes a streaming workflow job: events published under
        the job id, terminal status from the run row (workflows do not support
        yield_run_output)."""
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import QueueWorker

        store = InMemoryQueueStore()
        await store.enqueue_job(
            {
                "id": "wr1",
                "component_type": "workflow",
                "component_id": "wf-1",
                "session_id": "s1",
                "job_type": "run",
                "payload": {"input": "hi", "kwargs": {}, "stream": True},
                "status": "queued",
                "attempt": 0,
                "max_attempts": 1,
                "available_at": 0,
                "created_at": 0,
            }
        )

        class FakeWorkflow:
            id = "wf-1"
            db = None

            async def arun(self, **kwargs):
                assert kwargs["stream"] is True
                # Workflows reject yield_run_output - the worker must not pass it
                assert "yield_run_output" not in kwargs
                for c in ("a", "b"):
                    yield FakeEvent(c)

            async def aget_run_output(self, run_id, session_id, user_id=None):
                from types import SimpleNamespace

                # Deliberately a plain str: DB round-trips lose the enum, and the
                # terminal write must survive that (found live: stream stuck
                # RUNNING forever when complete_run choked on the str)
                return SimpleNamespace(run_id=run_id, status="COMPLETED")

        worker = QueueWorker(
            store=store,
            resolve_component=lambda t, i: FakeWorkflow(),
            config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
        )
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)

        assert (await store.get_job("wr1"))["status"] == "completed"
        assert await fresh_stream.get_event_count("wr1") == 2
        assert await fresh_stream.get_run_status("wr1") == RunStatus.completed

        received = [idx async for idx, _sse in fresh_stream.tail("wr1")]
        assert received == [0, 1]
