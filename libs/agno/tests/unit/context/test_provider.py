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
from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunStartedEvent,
    ToolCallStartedEvent,
)
from agno.utils.events import (
    create_model_request_started_event,
    create_reasoning_started_event,
    create_run_completed_event,
    create_run_output_content_event,
    create_run_started_event,
    create_tool_call_started_event,
)


async def _collect_tool_output(tool, **kwargs) -> str:
    """Collect final string output from a generator tool."""
    gen = await tool.entrypoint(**kwargs)
    result = ""
    async for chunk in gen:
        if isinstance(chunk, str):
            result = chunk
    return result


async def _collect_tool_chunks(tool, **kwargs) -> list:
    gen = await tool.entrypoint(**kwargs)
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


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


@pytest.mark.asyncio
async def test_query_tool_stamps_streamed_sub_agent_events_with_parent_run_id():
    final_output = RunOutput(
        run_id="child-run",
        session_id="s-1",
        agent_id="wiki-read",
        agent_name="Wiki Read",
        content="sub-agent answer",
    )

    class _StreamingAgent:
        async def arun(self, *args, **kwargs):
            yield RunStartedEvent(
                run_id="child-run",
                session_id="s-1",
                agent_id="wiki-read",
                agent_name="Wiki Read",
            )
            yield RunContentEvent(
                run_id="child-run",
                session_id="s-1",
                agent_id="wiki-read",
                agent_name="Wiki Read",
                content="sub-agent answer",
            )
            yield ToolCallStartedEvent(
                run_id="child-run",
                session_id="s-1",
                agent_id="wiki-read",
                agent_name="Wiki Read",
                tool=ToolExecution(tool_call_id="tool-1", tool_name="search_wiki"),
            )
            yield RunCompletedEvent(
                run_id="child-run",
                session_id="s-1",
                agent_id="wiki-read",
                agent_name="Wiki Read",
                content="sub-agent answer",
            )
            yield final_output

    class _SubAgentProvider(_EchoProvider):
        async def _aget_query_agent(self, run_context: RunContext | None):
            return _StreamingAgent()

    query_tool = _SubAgentProvider(id="wiki")._query_tool()
    rc = RunContext(run_id="parent-run", session_id="s-1", user_id="u-1")

    chunks = await _collect_tool_chunks(query_tool, question="hello", run_context=rc)
    event_chunks = [chunk for chunk in chunks if not isinstance(chunk, str)]

    assert event_chunks
    assert all(chunk.parent_run_id == "parent-run" for chunk in event_chunks)
    assert final_output.parent_run_id == "parent-run"
    assert json.loads(chunks[-1]) == {"text": "sub-agent answer"}


def test_agent_event_factories_preserve_parent_run_id():
    run_output = RunOutput(
        run_id="child-run",
        session_id="s-1",
        agent_id="wiki-read",
        agent_name="Wiki Read",
        parent_run_id="parent-run",
        content="sub-agent answer",
    )
    tool = ToolExecution(tool_call_id="tool-1", tool_name="search_wiki")

    events = [
        create_run_started_event(run_output),
        create_run_output_content_event(run_output, content="delta"),
        create_tool_call_started_event(run_output, tool),
        create_model_request_started_event(run_output, model="gpt-test", model_provider="openai"),
        create_reasoning_started_event(run_output),
        create_run_completed_event(run_output),
    ]

    assert all(event.parent_run_id == "parent-run" for event in events)


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
