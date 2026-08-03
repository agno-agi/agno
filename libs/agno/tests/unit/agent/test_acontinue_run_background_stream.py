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
            yield MagicMock(spec=RunOutputEvent)

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
    async def test_str_status_from_run_row_is_coerced(self):
        """DB round-trips can degrade the enum to a plain str; the terminal
        write must coerce it or complete_run treats it as non-terminal."""
        from agno.agent._run import _acontinue_run_background_stream
        from agno.run import RunStatus

        agent = MagicMock()
        agent.db = None
        run_context = MagicMock()

        session_run = MagicMock()
        session_run.status = "PAUSED"  # plain str from a DB read (enum .value)
        agent_session = MagicMock()
        agent_session.get_run.return_value = session_run

        async def empty_stream(*args, **kwargs):
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
