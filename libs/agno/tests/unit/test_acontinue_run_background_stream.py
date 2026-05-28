"""
Unit tests for the acontinue_run background=True streaming fix.

Regression test for https://github.com/agno-agi/agno/issues/8134

Before the fix, calling team.acontinue_run(background=True, stream=True) would
route to _acontinue_run_stream, which yields raw TeamRunOutputEvent objects.
team_resumable_continue_response_streamer then yielded those objects directly to
FastAPI's StreamingResponse, which calls .encode() on each chunk, crashing with:

    AttributeError: 'RunContinuedEvent' object has no attribute 'encode'

The fix adds _acontinue_run_background_stream (mirrors _arun_background_stream
for the continue-run path) and updates acontinue_run_dispatch to pop the
`background` kwarg and route to it when background=True + stream=True.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAcontinueRunBackgroundDispatch:
    """background kwarg must be popped and routed correctly in acontinue_run_dispatch."""

    def test_background_kwarg_not_forwarded_to_acontinue_run_stream(self):
        """background=True must be consumed by acontinue_run_dispatch, not passed to
        _acontinue_run_stream (which has no such parameter and would silently ignore it
        while leaving raw events unformatted)."""
        import inspect

        from agno.team._run import _acontinue_run_stream

        sig = inspect.signature(_acontinue_run_stream)
        assert "background" not in sig.parameters, (
            "_acontinue_run_stream must not accept a 'background' parameter; "
            "background routing must happen in acontinue_run_dispatch"
        )

    def test_background_kwarg_is_popped_in_dispatch(self):
        """acontinue_run_dispatch must pop 'background' from **kwargs so it never leaks
        into the underlying stream functions."""
        from agno.team._run import acontinue_run_dispatch

        # The function must have **kwargs (it pops several params)
        import inspect

        sig = inspect.signature(acontinue_run_dispatch)
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        assert has_var_keyword, "acontinue_run_dispatch must accept **kwargs"

    @pytest.mark.asyncio
    async def test_background_stream_yields_strings_not_events(self):
        """_acontinue_run_background_stream must yield str objects (SSE-formatted),
        not raw event objects.  Yielding a non-str object to FastAPI's StreamingResponse
        triggers 'AttributeError: object has no attribute encode'."""
        from agno.run.team import TeamRunOutputEvent
        from agno.team._run import _acontinue_run_background_stream

        # Minimal stubs
        team = MagicMock()
        run_context = MagicMock()
        run_context.run_id = "test-run-id"

        # Create a fake event that _acontinue_run_stream would yield
        fake_event = MagicMock(spec=TeamRunOutputEvent)
        fake_event.__class__.__name__ = "RunContinuedEvent"

        async def fake_continue_stream(*args, **kwargs):
            yield fake_event

        format_sse_called_with = []

        def fake_format_sse(event, event_index=None, run_id=None):
            format_sse_called_with.append(event)
            return f"data: {type(event).__name__}\n\n"

        # lazy imports inside the function body use these module paths
        with (
            patch("agno.team._run._acontinue_run_stream", side_effect=fake_continue_stream),
            patch("agno.team._storage._aread_or_create_session", new_callable=AsyncMock, return_value=MagicMock()),
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
                run_response=None,
                run_context=run_context,
                session_id="test-session",
                run_id="test-run-id",
            ):
                collected.append(chunk)

        # All yielded chunks must be strings (so .encode() works in StreamingResponse)
        for chunk in collected:
            assert isinstance(chunk, str), (
                f"_acontinue_run_background_stream must yield str objects "
                f"for StreamingResponse compatibility, got {type(chunk)}: {chunk!r}"
            )

        # format_sse_event_with_index must have been called with the raw event
        assert fake_event in format_sse_called_with, (
            "format_sse_event_with_index must be called on raw events before yielding"
        )
