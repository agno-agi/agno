"""Unit tests for the agent background continue-run stream producer
(_acontinue_run_background_stream): final-status derivation for HITL
continues that arrive with run_response=None."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_mock_event_stream() -> MagicMock:
    """Mock BaseEventStream: async methods, add_event assigns index 0."""
    stream = MagicMock()
    stream.register_run = AsyncMock()
    stream.set_run_status = AsyncMock()
    stream.add_event = AsyncMock(return_value=0)
    stream.complete_run = AsyncMock()
    return stream


class TestRePausedContinueFinalStatus:
    @pytest.mark.asyncio
    async def test_re_paused_continue_publishes_paused_not_completed(self):
        """pause -> continue -> SECOND HITL pause: HTTP continues arrive with
        run_response=None, and the old fallback published a COMPLETED sentinel
        for the re-paused run - key refreshing stopped and the next continue
        restarted indices. The final status must be derived from the run row."""
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus
        from agno.run.agent import RunOutputEvent

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.paused  # the leg ended in a second pause
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        async def pausing_stream(*args, **kwargs):
            # The leg's own persistence parks the pause on the run row. The
            # pre-set PAUSED no longer survives to the assertion point: since
            # the run-ID-only fix, the producer stamps the loaded run
            # PENDING/RUNNING at startup, exactly like the run_response path.
            yield MagicMock(spec=RunOutputEvent)
            session_run.status = RunStatus.paused

        mock_stream = make_mock_event_stream()
        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=pausing_stream),
            patch(
                "agno.agent._storage.aread_or_create_session",
                new_callable=AsyncMock,
                return_value=agent_session,
            ),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            async for _chunk in _acontinue_run_background_stream(
                agent,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                pass

        assert mock_stream.complete_run.call_args is not None
        assert mock_stream.complete_run.call_args.args[1] == RunStatus.paused, (
            "a re-paused continue must publish PAUSED, never a COMPLETED sentinel"
        )

    @pytest.mark.asyncio
    async def test_shutdown_cancellation_persists_cancelled_not_completed(self):
        """Task-level shutdown mid-continue: the producer must persist
        CANCELLED and the terminal sentinel must say CANCELLED - the old
        producer had no CancelledError handler, so complete_run's non-terminal
        coercion published a FALSE COMPLETED for the interrupted continue."""
        import asyncio

        import agno.agent._run as run_mod
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus
        from agno.run.agent import RunOutputEvent

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        started = asyncio.Event()

        async def hanging_stream(*args, **kwargs):
            yield MagicMock(spec=RunOutputEvent)
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=hanging_stream),
            patch(
                "agno.agent._storage.aread_or_create_session",
                new_callable=AsyncMock,
                return_value=agent_session,
            ),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock) as mock_save,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _acontinue_run_background_stream(agent, run_context=run_context, session_id="s-1", run_id="r-1")
            first = await gen.__anext__()
            assert isinstance(first, str)
            await asyncio.wait_for(started.wait(), timeout=2)

            producer_task = next(iter(run_mod._background_tasks - tasks_before))
            producer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer_task
            await gen.aclose()

        assert session_run.status == RunStatus.cancelled, "shutdown must persist CANCELLED on the run row"
        assert mock_save.await_count >= 1
        assert mock_stream.complete_run.call_args.args[1] == RunStatus.cancelled, (
            "the terminal sentinel must say CANCELLED, never a coerced COMPLETED"
        )

    @pytest.mark.asyncio
    async def test_shutdown_never_stamps_cancelled_over_a_re_pause(self):
        """A leg that already RE-PAUSED parked a valid, continuable HITL
        state; shutdown while the producer drains trailing events must not
        destroy it - the run row keeps PAUSED and the sentinel re-parks."""
        import asyncio

        import agno.agent._run as run_mod
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus
        from agno.run.agent import RunOutputEvent

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running  # overwritten by startup stamps either way
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        started = asyncio.Event()

        async def hanging_stream(*args, **kwargs):
            yield MagicMock(spec=RunOutputEvent)
            session_run.status = RunStatus.paused  # the leg re-pauses before hanging
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=hanging_stream),
            patch(
                "agno.agent._storage.aread_or_create_session",
                new_callable=AsyncMock,
                return_value=agent_session,
            ),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _acontinue_run_background_stream(agent, run_context=run_context, session_id="s-1", run_id="r-1")
            await gen.__anext__()
            await asyncio.wait_for(started.wait(), timeout=2)

            producer_task = next(iter(run_mod._background_tasks - tasks_before))
            producer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer_task
            await gen.aclose()

        assert session_run.status == RunStatus.paused, "shutdown must not stamp CANCELLED over a re-pause"
        assert mock_stream.complete_run.call_args.args[1] == RunStatus.paused, (
            "the sentinel must re-park the stream as PAUSED"
        )

    @pytest.mark.asyncio
    async def test_str_status_from_run_row_is_coerced(self):
        """DB round-trips can degrade the enum to a plain str; the terminal
        write must coerce it or complete_run treats it as non-terminal."""
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running  # overwritten by startup stamps either way
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        async def empty_stream(*args, **kwargs):
            # The leg parks the pause as a plain str (a DB round-trip shape)
            session_run.status = "PAUSED"
            return
            yield  # pragma: no cover

        mock_stream = make_mock_event_stream()
        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=empty_stream),
            patch(
                "agno.agent._storage.aread_or_create_session",
                new_callable=AsyncMock,
                return_value=agent_session,
            ),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
        ):
            async for _chunk in _acontinue_run_background_stream(
                agent,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                pass

        assert mock_stream.complete_run.call_args.args[1] == RunStatus.paused


class TestRunIdOnlyContinuePersistsStatus:
    """HITL continues arrive with run_response=None (the
    router passes only run_id), and both persistence points sat behind
    `if run_response:` - the run executed fine while the DB read PAUSED for
    the entire leg. The producer must load the run from the session it
    already holds and persist PENDING, then RUNNING; the continue dispatch
    itself still receives run_response=None untouched."""

    @pytest.mark.asyncio
    async def test_run_id_only_continue_persists_pending_then_running(self):
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus
        from agno.run.agent import RunOutputEvent

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        class RecordingRun:
            def __init__(self):
                self.run_id = "r-1"
                self.history = [RunStatus.paused]
                self._status = RunStatus.paused

            @property
            def status(self):
                return self._status

            @status.setter
            def status(self, value):
                self._status = value
                self.history.append(value)

        session_run = RecordingRun()
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        seen_dispatch_kwargs: dict = {}

        async def one_event_stream(*args, **kwargs):
            seen_dispatch_kwargs.update(kwargs)
            yield MagicMock(spec=RunOutputEvent)

        mock_stream = make_mock_event_stream()
        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=one_event_stream),
            patch(
                "agno.agent._storage.aread_or_create_session",
                new_callable=AsyncMock,
                return_value=agent_session,
            ),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.agent._run.apersist_run_transition", new_callable=AsyncMock) as mock_transition,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            async for _chunk in _acontinue_run_background_stream(
                agent,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                pass

        assert RunStatus.pending in session_run.history and RunStatus.running in session_run.history, (
            f"run-ID-only continue must persist PENDING and RUNNING; status history: {session_run.history}"
        )
        assert session_run.history.index(RunStatus.pending) < session_run.history.index(RunStatus.running)
        agent_session.upsert_run.assert_called_once_with(run=session_run)
        assert mock_transition.await_count >= 1
        assert mock_transition.await_args_list[0].args[3] is session_run
        assert seen_dispatch_kwargs.get("run_response") is None, (
            "the loaded run is for persistence only - the dispatch must still receive run_response=None"
        )
