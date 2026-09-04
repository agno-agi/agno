"""Tests for RunContext.input_content — query-aware callable tools factory (#8603).

The callable tools factory could already be resolved per run, but it had no access
to the current turn's user input, so it could not select tools by relevance to
what the user just asked. RunContext now carries input_content, populated from
run_input.input_content before tools are resolved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.run.base import RunContext
from agno.tools.function import Function
from agno.utils.callables import invoke_callable_factory


def _dummy_tool(x: str) -> str:
    return f"result: {x}"


def _make_run_context(input_content: Optional[Any] = None) -> RunContext:
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        input_content=input_content,
    )


# --- RunContext field exists and defaults to None ---


def test_input_content_defaults_to_none():
    ctx = RunContext(run_id="r", session_id="s")
    assert ctx.input_content is None


def test_input_content_can_be_set():
    ctx = RunContext(run_id="r", session_id="s", input_content="summarize the sales report")
    assert ctx.input_content == "summarize the sales report"


# --- the factory reads run_context.input_content for query-aware selection ---


def _query_aware_factory(run_context: RunContext) -> List[Any]:
    """A toy retriever: pick tools based on the user's query."""
    query = (run_context.input_content or "").lower()
    if "weather" in query:
        return [Function(name="get_weather", fn=_dummy_tool)]
    return [Function(name="calculator", fn=_dummy_tool)]


def test_factory_receives_input_content_and_selects_by_query():
    """The resolved run_context carries the turn input into the factory (#8603)."""
    ctx = _make_run_context(input_content="What's the weather in Tokyo?")
    tools = invoke_callable_factory(_query_aware_factory, entity=None, run_context=ctx)
    assert [t.name for t in tools] == ["get_weather"]


def test_factory_falls_back_when_query_matches_nothing():
    ctx = _make_run_context(input_content="calculate 2+2")
    tools = invoke_callable_factory(_query_aware_factory, entity=None, run_context=ctx)
    assert [t.name for t in tools] == ["calculator"]


def test_factory_handles_none_input_gracefully():
    """A factory must not crash when input_content is None (pre-run / non-string input)."""
    ctx = _make_run_context(input_content=None)
    tools = invoke_callable_factory(_query_aware_factory, entity=None, run_context=ctx)
    assert [t.name for t in tools] == ["calculator"]


# --- factories that don't ask for input_content are unaffected (backward compat) ---


def _role_scoped_factory(session_state: Optional[Dict[str, Any]]) -> List[Any]:
    """The documented pre-existing use case: pick tools by session role."""
    role = (session_state or {}).get("role")
    if role == "analyst":
        return [Function(name="run_query", fn=_dummy_tool)]
    return [Function(name="calculator", fn=_dummy_tool)]


def test_role_scoped_factory_unaffected_by_input_content_change():
    """Adding input_content must not disturb factories that ignore it."""
    ctx = RunContext(
        run_id="r",
        session_id="s",
        session_state={"role": "analyst"},
        input_content="anything",
    )
    tools = invoke_callable_factory(_role_scoped_factory, entity=None, run_context=ctx)
    assert [t.name for t in tools] == ["run_query"]
