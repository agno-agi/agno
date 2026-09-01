"""Task-level shutdown must not destroy a paused run.

A run that PAUSED for human input parked valid, continuable HITL state, and
the leg's own persistence wrote the PAUSED row. The shutdown branches in the
background producers stamped CANCELLED on whatever run they held with no
state check - a routine deploy killed every approval flow that happened to be
in flight. Only the continue-stream variants guarded; these tests pin the
guard on the primary producers (one representative per component - the guard
block is identical across each component's producer family).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.run.base import RunStatus


def make_mock_event_stream() -> MagicMock:
    stream = MagicMock()
    stream.register_run = AsyncMock()
    stream.set_run_status = AsyncMock()
    stream.add_event = AsyncMock(return_value=0)
    stream.complete_run = AsyncMock()
    return stream


class TestAgentStreamProducerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_preserves_pause(self):
        import agno.agent._run as run_mod
        from agno.agent._run import _arun_background_stream
        from agno.run.agent import RunOutput, RunOutputEvent

        agent = MagicMock()
        agent.db = None
        run_response = RunOutput(run_id="r-pause-a", session_id="s-1", status=RunStatus.running)
        started = asyncio.Event()

        async def pausing_then_hanging_stream(*args, **kwargs):
            yield MagicMock(spec=RunOutputEvent)
            # The leg pauses for HITL input (and persists PAUSED itself)
            run_response.status = RunStatus.paused
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.agent._run._arun_stream", side_effect=pausing_then_hanging_stream),
            patch("agno.agent._storage.aread_or_create_session", new_callable=AsyncMock, return_value=MagicMock()),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.agent._run.apersist_run_transition", new_callable=AsyncMock) as mock_transition,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _arun_background_stream(agent, run_response=run_response, run_context=MagicMock(), session_id="s-1")
            await gen.__anext__()
            await asyncio.wait_for(started.wait(), timeout=2)
            calls_before_shutdown = mock_transition.await_count

            producer_task = next(iter(run_mod._background_tasks - tasks_before))
            producer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer_task
            await gen.aclose()

        assert run_response.status == RunStatus.paused, (
            f"shutdown stamped {run_response.status} over a paused HITL run - the approval flow is dead"
        )
        assert mock_transition.await_count == calls_before_shutdown, (
            "shutdown must not persist anything over a paused run"
        )


class TestTeamStreamProducerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_preserves_pause(self):
        import agno.team._run as run_mod
        from agno.run.team import TeamRunOutput, TeamRunOutputEvent
        from agno.team._run import _arun_background_stream

        team = MagicMock()
        team.db = None
        run_response = TeamRunOutput(run_id="r-pause-t", session_id="s-1", status=RunStatus.running)
        started = asyncio.Event()

        async def pausing_then_hanging_stream(*args, **kwargs):
            yield MagicMock(spec=TeamRunOutputEvent)
            run_response.status = RunStatus.paused
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.team._run._arun_stream", side_effect=pausing_then_hanging_stream),
            patch("agno.team._storage._aread_or_create_session", new_callable=AsyncMock, return_value=MagicMock()),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.team._run.apersist_run_transition", new_callable=AsyncMock) as mock_transition,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _arun_background_stream(team, run_response=run_response, run_context=MagicMock(), session_id="s-1")
            await gen.__anext__()
            await asyncio.wait_for(started.wait(), timeout=2)
            calls_before_shutdown = mock_transition.await_count

            producer_task = next(iter(run_mod._background_tasks - tasks_before))
            producer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer_task
            await gen.aclose()

        assert run_response.status == RunStatus.paused, (
            f"shutdown stamped {run_response.status} over a paused HITL run - the approval flow is dead"
        )
        assert mock_transition.await_count == calls_before_shutdown


class TestWorkflowBackgroundShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_preserves_pause(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.workflow.workflow import Workflow

        wf = Workflow(id="wf-pause", name="WF", steps=[], db=SqliteDb(db_file=str(tmp_path / "w.db")))
        started = asyncio.Event()
        seen = {}

        async def pausing_then_hanging_execute(**kwargs):
            resp = kwargs["workflow_run_response"]
            seen["resp"] = resp
            resp.status = RunStatus.paused  # the leg pauses (and persists) itself
            started.set()
            await asyncio.sleep(3600)

        wf._aexecute = pausing_then_hanging_execute  # type: ignore[method-assign]
        with patch("agno.workflow.workflow.apersist_run_transition", new_callable=AsyncMock) as mock_transition:
            run_response = await wf._arun_background(input="hello", session_id="s-wf")
            await asyncio.wait_for(started.wait(), timeout=2)
            calls_before_shutdown = mock_transition.await_count

            producer_task = next(
                t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("workflow-background-")
            )
            producer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer_task

        assert seen["resp"] is run_response
        assert run_response.status == RunStatus.paused, (
            f"shutdown stamped {run_response.status} over a paused HITL run - the approval flow is dead"
        )
        assert mock_transition.await_count == calls_before_shutdown, (
            "shutdown must not persist anything over a paused run"
        )
