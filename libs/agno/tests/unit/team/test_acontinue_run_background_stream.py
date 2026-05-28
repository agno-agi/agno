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

import asyncio
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
            patch("agno.os.managers.event_buffer") as mock_eb,
            patch("agno.os.managers.sse_subscriber_manager") as mock_ssm,
            patch("agno.os.utils.format_sse_event_with_index", side_effect=fake_format_sse),
        ):
            mock_eb.add_event.return_value = 0
            mock_ssm.publish = AsyncMock()
            mock_ssm.complete = AsyncMock()

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
                f"_acontinue_run_background_stream must yield str (for StreamingResponse.encode()), "
                f"got {type(chunk)!r}"
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
        run_context = MagicMock()
        run_response = MagicMock()
        run_response.run_id = "r-1"
        run_response.status = None

        async def failing_stream(*args, **kwargs):
            raise RuntimeError("boom")
            yield  # pragma: no cover  (make it an async generator)

        team_session = MagicMock()

        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=failing_stream),
            patch(
                "agno.team._storage._aread_or_create_session",
                new_callable=AsyncMock,
                return_value=team_session,
            ),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._session.asave_session", new_callable=AsyncMock) as mock_save,
            patch("agno.os.managers.event_buffer") as mock_eb,
            patch("agno.os.managers.sse_subscriber_manager") as mock_ssm,
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            mock_eb.add_event.return_value = 0
            mock_ssm.publish = AsyncMock()
            mock_ssm.complete = AsyncMock()

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
        # asave_session is called at least twice: once for RUNNING, once for ERROR
        assert mock_save.await_count >= 2
        # SSE subscribers must be signaled even on failure (call_count covers either
        # direct await or asyncio.shield-wrapped await)
        assert mock_ssm.complete.call_count >= 1
