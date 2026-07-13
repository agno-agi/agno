"""Unit tests for sync team delegation routing MCP-backed members through arun()"""

import asyncio

import pytest

from agno.team import _member_execution as me

# Detection matches classes named exactly "MCPTools"/"MultiMCPTools"
class MCPTools:
    """Stand-in whose class name matches the MRO-based MCP detection."""


class MCPToolsSubclass(MCPTools):
    """Subclass to confirm detection walks the full MRO, not just the leaf class."""


class MultiMCPTools:
    """Stand-in for the multi-server MCP toolkit, matched by class name."""


class PlainToolkit:
    """A non-MCP toolkit that must never trigger the async bridge."""


class RecordingMember:
    """Minimal Agent-like member that records whether run() or arun() was used."""

    def __init__(self, tools=None, members=None, result="sync-result", astream_items=None):
        self.tools = tools
        # ``members`` is only read for Team-like members; harmless on an Agent stand-in.
        if members is not None:
            self.members = members
        self._result = result
        self._astream_items = astream_items or []
        self.run_called = False
        self.arun_called = False

    def run(self, **kwargs):
        self.run_called = True
        return self._result

    async def arun(self, **kwargs):
        self.arun_called = True
        # Confirm we are on a live event loop (the bridge's whole point).
        await asyncio.sleep(0)
        return f"async-{self._result}"


class RecordingStreamMember(RecordingMember):
    """Member whose arun() returns an async iterator, mirroring stream=True."""

    def run(self, **kwargs):
        self.run_called = True

        def _gen():
            yield from self._astream_items

        return _gen()

    def arun(self, **kwargs):
        self.arun_called = True

        async def _agen():
            for item in self._astream_items:
                await asyncio.sleep(0)
                yield item

        return _agen()


# --- Detection -------------------------------------------------------------


def test_detects_direct_mcp_tools():
    member = RecordingMember(tools=[PlainToolkit(), MCPTools()])
    assert me.member_has_mcp_tools(member) is True


def test_detects_mcp_tools_subclass_via_mro():
    member = RecordingMember(tools=[MCPToolsSubclass()])
    assert me.member_has_mcp_tools(member) is True


def test_detects_multi_mcp_tools():
    member = RecordingMember(tools=[MultiMCPTools()])
    assert me.member_has_mcp_tools(member) is True


def test_no_mcp_tools_is_false():
    member = RecordingMember(tools=[PlainToolkit()])
    assert me.member_has_mcp_tools(member) is False


def test_none_tools_is_false():
    assert me.member_has_mcp_tools(RecordingMember(tools=None)) is False


def test_callable_tools_factory_treated_as_non_mcp():
    # Callable factories are resolved later by arun(); the fast check must not
    # try to introspect them (and must not raise).
    member = RecordingMember(tools=lambda: [MCPTools()])
    assert me.member_has_mcp_tools(member) is False


def test_detects_mcp_in_nested_team_member():
    inner_agent = RecordingMember(tools=[MCPTools()])
    team_member = RecordingMember(tools=[PlainToolkit()], members=[inner_agent])
    assert me.member_has_mcp_tools(team_member) is True


def test_nested_team_without_mcp_is_false():
    inner_agent = RecordingMember(tools=[PlainToolkit()])
    team_member = RecordingMember(tools=None, members=[inner_agent])
    assert me.member_has_mcp_tools(team_member) is False


# --- run_member_sync routing ----------------------------------------------


def test_non_mcp_member_uses_sync_run():
    member = RecordingMember(tools=[PlainToolkit()], result="value")
    result = me.run_member_sync(member, input="hi")
    assert result == "value"
    assert member.run_called is True
    assert member.arun_called is False


def test_mcp_member_bridges_to_arun():
    member = RecordingMember(tools=[MCPTools()], result="value")
    result = me.run_member_sync(member, input="hi")
    assert result == "async-value"
    assert member.arun_called is True
    assert member.run_called is False


def test_run_member_sync_forwards_kwargs_to_run():
    seen = {}

    class KwargMember(RecordingMember):
        def run(self, **kwargs):
            seen.update(kwargs)
            return "ok"

    member = KwargMember(tools=[PlainToolkit()])
    me.run_member_sync(member, input="task", session_id="abc", stream=False)
    assert seen == {"input": "task", "session_id": "abc", "stream": False}


def test_run_member_sync_propagates_exception_from_arun():
    class FailingMember(RecordingMember):
        async def arun(self, **kwargs):
            await asyncio.sleep(0)
            raise ValueError("mcp boom")

    member = FailingMember(tools=[MCPTools()])
    with pytest.raises(ValueError, match="mcp boom"):
        me.run_member_sync(member, input="hi")


# --- stream_member_sync routing -------------------------------------------


def test_non_mcp_stream_uses_sync_run():
    member = RecordingStreamMember(tools=[PlainToolkit()], astream_items=["a", "b", "c"])
    items = list(me.stream_member_sync(member, input="hi", stream=True))
    assert items == ["a", "b", "c"]
    assert member.run_called is True
    assert member.arun_called is False


def test_mcp_stream_bridges_to_arun_preserving_order():
    member = RecordingStreamMember(tools=[MCPTools()], astream_items=[1, 2, 3, 4])
    items = list(me.stream_member_sync(member, input="hi", stream=True))
    assert items == [1, 2, 3, 4]
    assert member.arun_called is True
    assert member.run_called is False


def test_mcp_stream_propagates_exception():
    class FailingStreamMember(RecordingStreamMember):
        def arun(self, **kwargs):
            self.arun_called = True

            async def _agen():
                await asyncio.sleep(0)
                yield "first"
                raise RuntimeError("stream boom")

            return _agen()

    member = FailingStreamMember(tools=[MCPTools()])
    collected = []
    with pytest.raises(RuntimeError, match="stream boom"):
        for item in me.stream_member_sync(member, input="hi", stream=True):
            collected.append(item)
    # The item emitted before the error should still have been delivered.
    assert collected == ["first"]


def test_bridge_runs_on_a_real_event_loop_even_when_caller_has_none():
    # There must be no running loop on the calling thread; the bridge creates its
    # own. asyncio.get_running_loop() would raise here if we were inside a loop.
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()

    member = RecordingMember(tools=[MCPTools()], result="v")
    assert me.run_member_sync(member, input="hi") == "async-v"
