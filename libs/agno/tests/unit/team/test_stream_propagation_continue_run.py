"""Tests for stream= propagation through _route_requirements_to_members / _aroute_requirements_to_members.

Regression tests for https://github.com/agno-agi/agno/issues/7003
"""

import asyncio
from unittest.mock import MagicMock, patch

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement


def _make_requirement(**te_overrides) -> RunRequirement:
    defaults = dict(tool_name="do_something", tool_args={"x": 1})
    defaults.update(te_overrides)
    te = ToolExecution(**defaults)
    return RunRequirement(tool_execution=te)


def _make_routing_fixtures(member_id="member-1"):
    """Build the mocks needed by _route_requirements_to_members."""
    from agno.run.agent import RunOutput

    team = MagicMock()
    session = MagicMock()
    session.session_id = "sess-1"

    member = MagicMock()
    member.name = "TestAgent"

    # continue_run / acontinue_run return a non-paused response
    member_response = MagicMock(spec=RunOutput)
    member_response.is_paused = False
    member_response.content = "done"
    member.continue_run.return_value = member_response

    async def _async_continue(**kw):
        return member_response

    member.acontinue_run = MagicMock(side_effect=_async_continue)

    # Build a requirement that targets this member
    req = _make_requirement(requires_confirmation=True)
    req.member_agent_id = member_id
    req.member_run_id = "run-abc"

    # Attach a cached member run output so the run_response= path is taken
    cached_run_output = MagicMock(spec=RunOutput)
    cached_run_output.requirements = [req]
    cached_run_output.tools = None
    req._member_run_response = cached_run_output

    run_response = MagicMock()
    run_response.requirements = [req]

    return team, run_response, session, member, member_id


# ===========================================================================
# Sync: _route_requirements_to_members
# ===========================================================================


class TestSyncStreamPropagation:
    def test_stream_true_forwarded_via_run_response_path(self):
        from agno.team._run import _route_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response, session, stream=True)

        member.continue_run.assert_called_once()
        call_kwargs = member.continue_run.call_args[1]
        assert call_kwargs["stream"] is True
        assert call_kwargs["yield_run_output"] is True

    def test_stream_false_forwarded(self):
        from agno.team._run import _route_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response, session, stream=False)

        call_kwargs = member.continue_run.call_args[1]
        assert call_kwargs["stream"] is False
        assert call_kwargs["yield_run_output"] is False

    def test_stream_none_forwarded_by_default(self):
        from agno.team._run import _route_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response, session)

        call_kwargs = member.continue_run.call_args[1]
        assert call_kwargs["stream"] is None

    def test_stream_true_consumes_iterator(self):
        """When stream=True, the routing function should consume the iterator to extract RunOutput."""
        from agno.run.agent import RunOutput
        from agno.team._run import _route_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        # Simulate stream=True returning an iterator that yields events then RunOutput
        final_output = MagicMock(spec=RunOutput)
        final_output.is_paused = False
        final_output.content = "streamed result"
        member.continue_run.return_value = iter(["event1", "event2", final_output])

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            results = _route_requirements_to_members(team, run_response, session, stream=True)

        assert len(results) == 1
        assert "streamed result" in results[0]

    def test_stream_forwarded_via_run_id_fallback(self):
        """When _member_run_response is None, the run_id fallback path should also pass stream."""
        from agno.team._run import _route_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        # Clear the cached run output so the fallback path is used
        for req in run_response.requirements:
            req._member_run_response = None

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response, session, stream=True)

        call_kwargs = member.continue_run.call_args[1]
        assert call_kwargs["stream"] is True
        # Should use run_id path, not run_response path
        assert "run_id" in call_kwargs


# ===========================================================================
# Async: _aroute_requirements_to_members
# ===========================================================================


class TestAsyncStreamPropagation:
    def test_stream_true_forwarded_async(self):
        from agno.team._run import _aroute_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            asyncio.get_event_loop().run_until_complete(
                _aroute_requirements_to_members(team, run_response, session, stream=True)
            )

        member.acontinue_run.assert_called_once()
        call_kwargs = member.acontinue_run.call_args[1]
        assert call_kwargs["stream"] is True
        assert call_kwargs["yield_run_output"] is True

    def test_stream_true_consumes_async_iterator(self):
        """When stream=True, the async routing function should consume the async iterator."""
        from agno.run.agent import RunOutput
        from agno.team._run import _aroute_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        final_output = MagicMock(spec=RunOutput)
        final_output.is_paused = False
        final_output.content = "async streamed result"

        async def _async_stream(**kw):
            async def _gen():
                yield "event1"
                yield "event2"
                yield final_output

            return _gen()

        member.acontinue_run = MagicMock(side_effect=_async_stream)

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            results = asyncio.get_event_loop().run_until_complete(
                _aroute_requirements_to_members(team, run_response, session, stream=True)
            )

        assert len(results) == 1
        assert "async streamed result" in results[0]

    def test_stream_none_by_default_async(self):
        from agno.team._run import _aroute_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            asyncio.get_event_loop().run_until_complete(_aroute_requirements_to_members(team, run_response, session))

        call_kwargs = member.acontinue_run.call_args[1]
        assert call_kwargs["stream"] is None

    def test_stream_forwarded_via_run_id_fallback_async(self):
        from agno.team._run import _aroute_requirements_to_members

        team, run_response, session, member, mid = _make_routing_fixtures()

        for req in run_response.requirements:
            req._member_run_response = None

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            asyncio.get_event_loop().run_until_complete(
                _aroute_requirements_to_members(team, run_response, session, stream=True)
            )

        call_kwargs = member.acontinue_run.call_args[1]
        assert call_kwargs["stream"] is True
        assert "run_id" in call_kwargs
