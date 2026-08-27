"""Unit tests for team acontinue_run(background=True, stream=True).

Regression tests for https://github.com/agno-agi/agno/issues/8134

Before the fix, team.acontinue_run(background=True, stream=True) routed to
_acontinue_run_stream which yields raw TeamRunOutputEvent objects.
team_resumable_continue_response_streamer then yielded those objects directly
to FastAPI's StreamingResponse, which calls .encode() on each chunk and
crashed with:

    AttributeError: 'RunContinuedEvent' object has no attribute 'encode'

The fix adds _acontinue_run_background_stream (mirrors _arun_background_stream
for the continue-run path) and updates acontinue_run_dispatch to route to it
when background=True and stream=True.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAcontinueRunBackgroundDispatchSignature:
    """`background` must be a typed parameter on dispatch (not pulled from **kwargs)."""

    def test_dispatch_exposes_typed_background_parameter(self):
        """acontinue_run_dispatch must declare `background: bool` explicitly so the
        team API surface stays in lock-step with Agent.acontinue_run_dispatch."""
        from agno.team._run import acontinue_run_dispatch

        sig = inspect.signature(acontinue_run_dispatch)
        assert "background" in sig.parameters, "acontinue_run_dispatch must declare `background` explicitly"
        param = sig.parameters["background"]
        assert param.default is False, "background must default to False"
        # Module uses PEP 563 postponed annotations — annotation may be the string "bool"
        assert param.annotation in (bool, "bool"), "background must be annotated as bool"

    def test_acontinue_run_stream_does_not_accept_background(self):
        """_acontinue_run_stream must not accept `background` — it is consumed by the
        dispatch layer. If it leaked, raw events would reach StreamingResponse and
        trigger the AttributeError from issue #8134."""
        from agno.team._run import _acontinue_run_stream

        sig = inspect.signature(_acontinue_run_stream)
        assert "background" not in sig.parameters

    def test_team_acontinue_run_exposes_typed_background_parameter(self):
        """Team.acontinue_run mirrors Agent.acontinue_run by surfacing `background`
        as a typed parameter (not a stray **kwarg)."""
        from agno.team.team import Team

        sig = inspect.signature(Team.acontinue_run)
        assert "background" in sig.parameters
        assert sig.parameters["background"].default is False


class TestAcontinueRunBackgroundDispatchRouting:
    """background=True + stream=True must route to _acontinue_run_background_stream."""

    def test_background_stream_requires_db(self):
        """Without a configured db, background execution must raise a clear ValueError
        — mirrors arun_dispatch and the Agent acontinue_run dispatch."""
        from agno.team._run import acontinue_run_dispatch

        team = MagicMock()
        team.db = None  # no database configured
        team.session_id = "s"

        with pytest.raises(ValueError, match="Background execution requires a database"):
            acontinue_run_dispatch(
                team,
                run_id="r-1",
                session_id="s-1",
                stream=True,
                background=True,
            )


def make_mock_event_stream() -> MagicMock:
    """Mock BaseEventStream: async methods, add_event assigns index 0."""
    stream = MagicMock()
    stream.register_run = AsyncMock()
    stream.set_run_status = AsyncMock()
    stream.add_event = AsyncMock(return_value=0)
    stream.complete_run = AsyncMock()
    return stream


class TestAcontinueRunBackgroundStream:
    """The helper itself must yield SSE-formatted strings (issue #8134 regression)."""

    @pytest.mark.asyncio
    async def test_yields_strings_not_events(self):
        """_acontinue_run_background_stream must yield str objects so that
        StreamingResponse's .encode() works. Yielding raw events triggers
        'AttributeError: 'RunContinuedEvent' object has no attribute 'encode''."""
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        run_context = MagicMock()

        fake_event = MagicMock(spec=TeamRunOutputEvent)

        async def fake_continue_stream(*args, **kwargs):
            yield fake_event

        format_sse_seen = []

        def fake_format_sse(event, event_index=None, run_id=None):
            format_sse_seen.append(event)
            return "data: payload\n\n"

        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=fake_continue_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=make_mock_event_stream()),
            patch("agno.os.utils.format_sse_event_with_index", side_effect=fake_format_sse),
        ):
            collected = []
            async for chunk in _acontinue_run_background_stream(
                team,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                collected.append(chunk)

        assert collected, "background stream must yield at least one chunk"
        for chunk in collected:
            assert isinstance(chunk, str), (
                f"_acontinue_run_background_stream must yield str (for StreamingResponse.encode()), got {type(chunk)!r}"
            )
        assert fake_event in format_sse_seen, "raw events must go through format_sse_event_with_index"

    @pytest.mark.asyncio
    async def test_persists_error_status_on_failure(self):
        """When the inner _acontinue_run_stream raises, the helper must persist
        RunStatus.error and still terminate the SSE queue cleanly — matches
        _arun_background_stream behavior."""
        from agno.run import RunStatus
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        # No DB on the mock: apersist_run_transition takes its fallback path
        # (fresh-read + asave_session), which this test asserts on.
        team.db = None
        run_context = MagicMock()
        run_response = MagicMock()
        run_response.run_id = "r-1"
        run_response.status = None

        async def failing_stream(*args, **kwargs):
            raise RuntimeError("boom")
            yield  # pragma: no cover  (make it an async generator)

        stored_run = MagicMock()
        stored_run.run_id = "r-1"
        stored_run.status = RunStatus.running
        team_session = MagicMock()
        team_session.runs = [stored_run]

        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=failing_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch(
                "agno.team._storage._aread_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock) as mock_save,
            patch("agno.os.event_streams.get_event_stream", return_value=(mock_stream := make_mock_event_stream())),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            collected = []
            async for chunk in _acontinue_run_background_stream(
                team,
                run_context=run_context,
                session_id="s-1",
                run_response=run_response,
            ):
                collected.append(chunk)

        # The error path must have set RunStatus.error on the run_response
        assert run_response.status == RunStatus.error, "background helper must persist RunStatus.error on failure"
        # asave_session is called at least twice: once for RUNNING, once for
        # ERROR, which is only written over a stored run still carrying the
        # RUNNING marker step 1 wrote
        assert mock_save.await_count >= 2
        # The event stream must be marked terminal even on failure (call_count
        # covers either direct await or asyncio.shield-wrapped await)
        assert mock_stream.complete_run.call_count >= 1


class TestRePausedContinueFinalStatus:
    @pytest.mark.asyncio
    async def test_re_paused_continue_publishes_paused_not_completed(self):
        """pause -> continue -> SECOND HITL pause: HTTP continues arrive with
        run_response=None, and the old fallback published a COMPLETED sentinel
        for the re-paused run - key refreshing stopped and the next continue
        restarted indices. The final status must be derived from the run row."""
        from agno.run import RunStatus
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.paused  # the leg ended in a second pause
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        async def pausing_stream(*args, **kwargs):
            # The leg's own persistence parks the pause on the run row. The
            # pre-set PAUSED no longer survives to the assertion point: since
            # the run-ID-only fix, the producer stamps the loaded run
            # PENDING/RUNNING at startup, exactly like the run_response path.
            yield MagicMock(spec=TeamRunOutputEvent)
            session_run.status = RunStatus.paused

        mock_stream = make_mock_event_stream()
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=pausing_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            async for _chunk in _acontinue_run_background_stream(
                team,
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

        import agno.team._run as run_mod
        from agno.run import RunStatus
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        started = asyncio.Event()

        async def hanging_stream(*args, **kwargs):
            yield MagicMock(spec=TeamRunOutputEvent)
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=hanging_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock) as mock_save,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _acontinue_run_background_stream(team, run_context=run_context, session_id="s-1", run_id="r-1")
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

        import agno.team._run as run_mod
        from agno.run import RunStatus
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running  # overwritten by startup stamps either way
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        started = asyncio.Event()

        async def hanging_stream(*args, **kwargs):
            yield MagicMock(spec=TeamRunOutputEvent)
            session_run.status = RunStatus.paused  # the leg re-pauses before hanging
            started.set()
            await asyncio.sleep(3600)

        mock_stream = make_mock_event_stream()
        tasks_before = set(run_mod._background_tasks)
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=hanging_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            gen = _acontinue_run_background_stream(team, run_context=run_context, session_id="s-1", run_id="r-1")
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
        from agno.run import RunStatus
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.running  # overwritten by startup stamps either way
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        async def empty_stream(*args, **kwargs):
            # The leg parks the pause as a plain str (a DB round-trip shape)
            session_run.status = "PAUSED"
            return
            yield  # pragma: no cover

        mock_stream = make_mock_event_stream()
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=empty_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
        ):
            async for _chunk in _acontinue_run_background_stream(
                team,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                pass

        assert mock_stream.complete_run.call_args.args[1] == RunStatus.paused


class TestQueuedCancelWithoutRunResponse:
    @pytest.mark.asyncio
    async def test_cancel_of_hitl_continue_persists_cancelled_not_completed(self):
        """HITL continues arrive with run_response=None. Cancelling one while
        queued must persist CANCELLED (loaded from the session) and mark the
        event stream CANCELLED - never COMPLETED for a run that never executed."""
        from agno.exceptions import RunCancelledException
        from agno.run import RunStatus
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None  # helper falls back to the session-save path
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = RunStatus.paused
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        mock_stream = make_mock_event_stream()

        with (
            patch("agno.team._run.background_run_slot") as mock_slot,
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock) as mock_save,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.team._run.acleanup_run", new_callable=AsyncMock),
        ):
            mock_slot.return_value.__aenter__ = AsyncMock(side_effect=RunCancelledException("r-1"))
            mock_slot.return_value.__aexit__ = AsyncMock()

            collected = []
            async for chunk in _acontinue_run_background_stream(
                team,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                collected.append(chunk)

        # The session run (loaded by run_id) was persisted as CANCELLED
        assert session_run.status == RunStatus.cancelled
        assert mock_save.await_count >= 1
        # The event stream was marked CANCELLED, not COMPLETED
        assert mock_stream.complete_run.call_args is not None
        assert mock_stream.complete_run.call_args.args[1] == RunStatus.cancelled


class TestRunIdOnlyContinuePersistsStatus:
    """Team twin of the agent test: run-ID-only continues must persist
    PENDING then RUNNING from the session-loaded run; the dispatch still
    receives run_response=None. See the agent twin for the full story."""

    @pytest.mark.asyncio
    async def test_run_id_only_continue_persists_pending_then_running(self):
        from unittest.mock import AsyncMock, patch

        from agno.run import RunStatus
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        team = MagicMock()
        team.db = None
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
        team_session = MagicMock()
        team_session.get_run.return_value = session_run

        seen_dispatch_kwargs: dict = {}

        async def one_event_stream(*args, **kwargs):
            seen_dispatch_kwargs.update(kwargs)
            yield MagicMock(spec=TeamRunOutputEvent)

        mock_stream = MagicMock()
        mock_stream.register_run = AsyncMock()
        mock_stream.set_run_status = AsyncMock()
        mock_stream.add_event = AsyncMock(return_value=0)
        mock_stream.complete_run = AsyncMock()
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=one_event_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock),
            patch("agno.team._run.apersist_run_transition", new_callable=AsyncMock) as mock_transition,
            patch("agno.os.event_streams.get_event_stream", return_value=mock_stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            async for _chunk in _acontinue_run_background_stream(
                team,
                run_context=run_context,
                session_id="s-1",
                run_id="r-1",
            ):
                pass

        assert RunStatus.pending in session_run.history and RunStatus.running in session_run.history, (
            f"run-ID-only continue must persist PENDING and RUNNING; status history: {session_run.history}"
        )
        assert session_run.history.index(RunStatus.pending) < session_run.history.index(RunStatus.running)
        team_session.upsert_run.assert_called_once_with(run_response=session_run)
        assert mock_transition.await_count >= 1
        assert mock_transition.await_args_list[0].args[3] is session_run
        assert seen_dispatch_kwargs.get("run_response") is None, (
            "the loaded run is for persistence only - the dispatch must still receive run_response=None"
        )
