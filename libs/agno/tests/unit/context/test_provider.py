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
# _query_tool — happy + error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_serializes_answer_text():
    p = _EchoProvider(id="e")
    query_tool = p._query_tool()
    out = await query_tool.entrypoint(question="hello")
    payload = json.loads(out)
    assert payload == {"results": [], "text": "q:hello"}


@pytest.mark.asyncio
async def test_query_tool_catches_aquery_exceptions():
    p = _RaisingQueryProvider(id="e")
    query_tool = p._query_tool()
    out = await query_tool.entrypoint(question="hello")
    payload = json.loads(out)
    # Error is reported as a string — the calling agent sees it but
    # isn't crashed.
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "aquery boom" in payload["error"]


@pytest.mark.asyncio
async def test_query_tool_omits_text_when_answer_text_is_none():
    class _DocsOnly(_EchoProvider):
        async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
            return Answer()

    tool_ = _DocsOnly(id="e")._query_tool()
    out = await tool_.entrypoint(question="hello")
    payload = json.loads(out)
    assert "text" not in payload
    assert payload["results"] == []


# ---------------------------------------------------------------------------
# _update_tool — happy, error, read-only paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tool_happy_path():
    p = _WritableProvider(id="w")
    tool_ = p._update_tool()
    out = await tool_.entrypoint(instruction="add x")
    payload = json.loads(out)
    assert payload == {"results": [], "text": "u:add x"}


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
    await query_tool.entrypoint(question="hello", run_context=rc)
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
