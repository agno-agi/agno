"""Unit tests for the ContextProvider ABC.

Focus on the tool-wrapping layer — what callers actually see when
`aquery` / `aupdate` raise, when `aupdate` is not overridden, etc.
These are the contract edges that _query_tool / _update_tool have to
catch before reaching the calling agent.
"""

from __future__ import annotations

import json

import pytest

from agno.context import Answer, ContextMode, ContextProvider, Status
from agno.context.provider import _sanitize_id
from agno.run import RunContext


async def _collect_tool_output(tool, **kwargs) -> str:
    """Collect final string output from a generator tool."""
    gen = await tool.entrypoint(**kwargs)
    result = ""
    async for chunk in gen:
        if isinstance(chunk, str):
            result = chunk
    return result


# ---------------------------------------------------------------------------
# Test fixtures — minimal providers that pass / raise on demand
# ---------------------------------------------------------------------------


class _EchoProvider(ContextProvider):
    """Returns the question back as text. For happy-path exercises."""

    def status(self) -> Status:
        return Status(ok=True, detail="echo")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=f"q:{question}")

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=f"q:{question}")


class _RaisingQueryProvider(_EchoProvider):
    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        raise RuntimeError("aquery boom")


class _WritableProvider(_EchoProvider):
    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=f"u:{instruction}")


class _RaisingWritableProvider(_EchoProvider):
    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        raise ValueError("aupdate boom")


# ---------------------------------------------------------------------------
# _sanitize_id
# ---------------------------------------------------------------------------


def test_sanitize_id_normalizes_case_and_punctuation():
    assert _sanitize_id("My-Provider.2") == "my_provider_2"


def test_sanitize_id_empty_input_defaults():
    assert _sanitize_id("!!!") == "context"


# ---------------------------------------------------------------------------
# Tool-name derivation
# ---------------------------------------------------------------------------


def test_default_tool_names_derive_from_id():
    p = _EchoProvider(id="MyThing")
    assert p.query_tool_name == "query_mything"
    assert p.update_tool_name == "update_mything"


def test_explicit_tool_names_override():
    p = _EchoProvider(id="x", query_tool_name="ask_x", update_tool_name="write_x")
    assert p.query_tool_name == "ask_x"
    assert p.update_tool_name == "write_x"


# ---------------------------------------------------------------------------
# get_tools() — mode resolution
# ---------------------------------------------------------------------------


def test_mode_default_returns_default_tools():
    p = _EchoProvider(id="e")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_e"]


def test_mode_agent_returns_just_query_tool():
    p = _EchoProvider(id="e", mode=ContextMode.agent)
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_e"]


def test_mode_tools_returns_all_tools():
    p = _EchoProvider(id="e", mode=ContextMode.tools)
    tools = p.get_tools()
    # base class _all_tools returns [_query_tool()]
    assert [t.name for t in tools] == ["query_e"]


# ---------------------------------------------------------------------------
# read / write flags — applied via the _read_write_tools helper that
# read+write subclasses call from their _default_tools override.
# ---------------------------------------------------------------------------


class _TwoToolProvider(_EchoProvider):
    """Subclass that exposes both query and update — uses the helper."""

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=f"u:{instruction}")

    def _default_tools(self) -> list:
        return self._read_write_tools()


def test_read_write_helper_default_returns_both_tools():
    p = _TwoToolProvider(id="x")
    assert [t.name for t in p.get_tools()] == ["query_x", "update_x"]


def test_read_write_helper_drops_update_when_write_false():
    p = _TwoToolProvider(id="x", write=False)
    assert [t.name for t in p.get_tools()] == ["query_x"]


def test_read_write_helper_drops_query_when_read_false():
    p = _TwoToolProvider(id="x", read=False)
    assert [t.name for t in p.get_tools()] == ["update_x"]


def test_both_flags_false_raises():
    with pytest.raises(ValueError, match="at least one of `read` or `write`"):
        _TwoToolProvider(id="x", read=False, write=False)


def test_read_write_flags_default_to_true():
    p = _EchoProvider(id="e")
    assert p.read is True
    assert p.write is True


def test_mode_agent_silently_ignores_read_false():
    """Per the design call: mode=agent + read=False is silently allowed.

    Behaviour-locking test — if we ever decide to raise, this is the
    test that flips. mode-mode interactions stay in their lane today.
    """
    p = _EchoProvider(id="e", mode=ContextMode.agent, read=False)
    tools = p.get_tools()
    # mode=agent always returns [query_tool] regardless of read.
    assert [t.name for t in tools] == ["query_e"]


# ---------------------------------------------------------------------------
# _query_tool — happy + error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_serializes_answer_text():
    p = _EchoProvider(id="e")
    query_tool = p._query_tool()
    out = await _collect_tool_output(query_tool, question="hello")
    payload = json.loads(out)
    # Empty `results` is omitted — no provider populates Document
    # results today, and shipping `"results": []` on every call is
    # filler the calling agent has to read past.
    assert payload == {"text": "q:hello"}


@pytest.mark.asyncio
async def test_query_tool_catches_aquery_exceptions():
    p = _RaisingQueryProvider(id="e")
    query_tool = p._query_tool()
    out = await _collect_tool_output(query_tool, question="hello")
    payload = json.loads(out)
    # Error is reported as a string — the calling agent sees it but
    # isn't crashed.
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "aquery boom" in payload["error"]


@pytest.mark.asyncio
async def test_query_tool_omits_both_when_answer_is_empty():
    """Both fields absent → empty payload. Honest "tool returned nothing" signal."""

    class _DocsOnly(_EchoProvider):
        async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
            return Answer()

    tool_ = _DocsOnly(id="e")._query_tool()
    out = await _collect_tool_output(tool_, question="hello")
    payload = json.loads(out)
    assert payload == {}


@pytest.mark.asyncio
async def test_query_tool_includes_results_when_populated():
    """When a provider does populate Document results, they're serialized."""
    from agno.context.provider import Document

    class _WithDocs(_EchoProvider):
        async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
            return Answer(
                results=[Document(id="d1", name="Page 1", uri="/p/1", snippet="hello")],
                text="see results",
            )

    tool_ = _WithDocs(id="e")._query_tool()
    out = await _collect_tool_output(tool_, question="hello")
    payload = json.loads(out)
    assert payload["text"] == "see results"
    assert payload["results"] == [{"id": "d1", "name": "Page 1", "uri": "/p/1", "source": None, "snippet": "hello"}]


# ---------------------------------------------------------------------------
# _update_tool — happy, error, read-only paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tool_happy_path():
    p = _WritableProvider(id="w")
    tool_ = p._update_tool()
    out = await tool_.entrypoint(instruction="add x")
    payload = json.loads(out)
    assert payload == {"text": "u:add x"}


@pytest.mark.asyncio
async def test_update_tool_reports_read_only_when_not_overridden():
    p = _EchoProvider(id="ro")  # no aupdate override -> base raises NotImplementedError
    tool_ = p._update_tool()
    out = await tool_.entrypoint(instruction="add x")
    payload = json.loads(out)
    # Specifically a read-only message, not a generic exception string —
    # the calling agent should be able to learn from this and not retry.
    assert payload == {"error": f"{p.name} is read-only"}


@pytest.mark.asyncio
async def test_update_tool_catches_aupdate_exceptions():
    p = _RaisingWritableProvider(id="w")
    tool_ = p._update_tool()
    out = await tool_.entrypoint(instruction="add x")
    payload = json.loads(out)
    assert "error" in payload
    assert "ValueError" in payload["error"]
    assert "aupdate boom" in payload["error"]


# ---------------------------------------------------------------------------
# RunContext propagation — the wrapper should thread run_context from the
# calling agent's auto-injection into provider.aquery / aupdate, and the
# `_run_kwargs_for_sub_agent` helper should extract the right fields.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_forwards_run_context_to_aquery():
    captured: dict = {}

    class _Captor(_EchoProvider):
        async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
            captured["run_context"] = run_context
            return Answer(text=f"q:{question}")

    p = _Captor(id="c")
    query_tool = p._query_tool()
    rc = RunContext(run_id="r-1", user_id="u-1", session_id="s-1", metadata={"action_token": "xoxa-abc"})
    # Framework would normally inject run_context via Function._run_context;
    # calling the entrypoint directly with run_context= simulates that path.
    await _collect_tool_output(query_tool, question="hello", run_context=rc)
    assert captured["run_context"] is rc


@pytest.mark.asyncio
async def test_update_tool_forwards_run_context_to_aupdate():
    captured: dict = {}

    class _WCaptor(_EchoProvider):
        async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
            captured["run_context"] = run_context
            return Answer(text=f"u:{instruction}")

    p = _WCaptor(id="w")
    update_tool = p._update_tool()
    rc = RunContext(run_id="r-2", session_id="s-2", user_id="u-2", dependencies={"db_url": "postgres://..."})
    await update_tool.entrypoint(instruction="write x", run_context=rc)
    assert captured["run_context"] is rc


def test_run_kwargs_for_sub_agent_extracts_only_populated_fields():
    # None -> empty dict (no kwargs injected)
    assert _EchoProvider(id="e")._run_kwargs_for_sub_agent(None) == {}

    # Fields with truthy values are extracted
    rc = RunContext(
        run_id="r-3",
        user_id="u-1",
        session_id="s-1",
        metadata={"action_token": "xoxa-abc"},
        dependencies={"tenant": "acme"},
    )
    kwargs = _EchoProvider(id="e")._run_kwargs_for_sub_agent(rc)
    assert kwargs == {
        "user_id": "u-1",
        "session_id": "s-1",
        "metadata": {"action_token": "xoxa-abc"},
        "dependencies": {"tenant": "acme"},
    }


def test_run_kwargs_for_sub_agent_drops_empty_fields():
    # Empty dict / empty string / None values should NOT be propagated,
    # so sub-agent defaults aren't silently overridden with empty data.
    rc = RunContext(run_id="r-4", user_id="", session_id="only-session", metadata={}, dependencies=None)
    kwargs = _EchoProvider(id="e")._run_kwargs_for_sub_agent(rc)
    assert kwargs == {"session_id": "only-session"}


# ---------------------------------------------------------------------------
# Base asetup() / aclose() are safe no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_aclose_is_noop():
    p = _EchoProvider(id="e")
    # Must not raise even though no session was ever opened.
    await p.aclose()


@pytest.mark.asyncio
async def test_base_asetup_is_noop():
    p = _EchoProvider(id="e")
    # Providers without async resources get a free pass on the hook.
    await p.asetup()


@pytest.mark.asyncio
async def test_base_asetup_is_idempotent():
    p = _EchoProvider(id="e")
    # Calling asetup() multiple times must be safe so callers can wire it
    # into a lifespan without tracking state themselves.
    await p.asetup()
    await p.asetup()


# ---------------------------------------------------------------------------
# Event streaming tests — verify events ARE yielded (the point of the PR)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_yields_events_from_sub_agent():
    """Events from the sub-agent must be yielded, not just the final answer."""
    from agno.run.agent import RunOutput

    class _FakeEvent:
        def __init__(self, name: str):
            self.name = name
            self.parent_run_id = None

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    yield _FakeEvent("event1")
                    yield _FakeEvent("event2")
                    yield RunOutput(content="final answer")

            return _FakeAgent()

    p = _StreamingProvider(id="s")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    events = []
    final_json = None
    async for chunk in gen:
        if isinstance(chunk, str):
            final_json = chunk
        else:
            events.append(chunk)

    assert len(events) == 2, f"Expected 2 events, got {len(events)}"
    assert events[0].name == "event1"
    assert events[1].name == "event2"
    assert final_json is not None
    assert "final answer" in final_json


@pytest.mark.asyncio
async def test_query_tool_sets_parent_run_id_on_events():
    """Each yielded event must have parent_run_id set to the parent's run_id."""
    from agno.run.agent import RunOutput

    class _FakeEvent:
        def __init__(self):
            self.parent_run_id = None

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    yield _FakeEvent()
                    yield _FakeEvent()
                    yield RunOutput(content="done")

            return _FakeAgent()

    p = _StreamingProvider(id="s")
    query_tool = p._query_tool()
    rc = RunContext(run_id="parent-run-123", user_id="u", session_id="s")
    gen = await query_tool.entrypoint(question="test", run_context=rc)

    events = []
    async for chunk in gen:
        if not isinstance(chunk, str):
            events.append(chunk)

    assert len(events) == 2
    for event in events:
        assert event.parent_run_id == "parent-run-123", (
            f"Expected parent_run_id='parent-run-123', got '{event.parent_run_id}'"
        )


@pytest.mark.asyncio
async def test_query_tool_preserves_existing_parent_run_id():
    """If event already has parent_run_id, don't overwrite it (nested sub-agents)."""
    from agno.run.agent import RunOutput

    class _FakeEvent:
        def __init__(self, parent_run_id=None):
            self.parent_run_id = parent_run_id

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    yield _FakeEvent(parent_run_id="nested-parent-456")
                    yield _FakeEvent(parent_run_id=None)
                    yield RunOutput(content="done")

            return _FakeAgent()

    p = _StreamingProvider(id="s")
    query_tool = p._query_tool()
    rc = RunContext(run_id="outer-parent-123", user_id="u", session_id="s")
    gen = await query_tool.entrypoint(question="test", run_context=rc)

    events = []
    async for chunk in gen:
        if not isinstance(chunk, str):
            events.append(chunk)

    assert events[0].parent_run_id == "nested-parent-456", "Should preserve existing parent_run_id"
    assert events[1].parent_run_id == "outer-parent-123", "Should set parent_run_id when None"


@pytest.mark.asyncio
async def test_streaming_path_and_aquery_path_both_work():
    """Provider without _aget_query_agent falls back to aquery (no streaming)."""
    p = _EchoProvider(id="e")
    query_tool = p._query_tool()
    out = await _collect_tool_output(query_tool, question="hello")
    payload = json.loads(out)
    assert payload["text"] == "q:hello"


@pytest.mark.asyncio
async def test_streaming_path_handles_no_run_context():
    """Streaming works even when run_context is None (parent_run_id will be None)."""
    from agno.run.agent import RunOutput

    class _FakeEvent:
        def __init__(self):
            self.parent_run_id = None

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    yield _FakeEvent()
                    yield RunOutput(content="done")

            return _FakeAgent()

    p = _StreamingProvider(id="s")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test", run_context=None)

    events = []
    async for chunk in gen:
        if not isinstance(chunk, str):
            events.append(chunk)

    assert len(events) == 1
    assert events[0].parent_run_id is None


@pytest.mark.asyncio
async def test_stream_sub_agent_events_flag_is_passed_to_sub_agent():
    """The stream_sub_agent_events flag should be passed to agent.arun()."""
    captured_kwargs = {}

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    captured_kwargs.update(kwargs)
                    from agno.run.agent import RunOutput

                    yield RunOutput(content="done")

            return _FakeAgent()

    p = _StreamingProvider(id="s", stream_sub_agent_events=True)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")
    async for _ in gen:
        pass

    assert captured_kwargs.get("stream") is True
    assert captured_kwargs.get("stream_events") is True


@pytest.mark.asyncio
async def test_stream_sub_agent_events_can_be_disabled():
    """stream_sub_agent_events=False should disable event streaming."""
    captured_kwargs = {}

    class _StreamingProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context):
            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    captured_kwargs.update(kwargs)
                    from agno.run.agent import RunOutput

                    yield RunOutput(content="done")

            return _FakeAgent()

    p = _StreamingProvider(id="s", stream_sub_agent_events=False)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")
    async for _ in gen:
        pass

    assert captured_kwargs.get("stream_events") is False
