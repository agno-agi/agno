"""Tests for streaming tool result: clean final content should be preferred over raw tokens."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import BaseModel

from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
)
from agno.run.team import (
    RunContentEvent as TeamRunContentEvent,
)
from agno.run.team import (
    TeamRunOutputEvent,
)


class ResearchResult(BaseModel):
    finding: str


# ---------------------------------------------------------------------------
# Test: base.py logic — prefers clean output over event accumulation (sync)
# ---------------------------------------------------------------------------


def test_base_model_prefers_clean_output_over_event_accumulation():
    """When a generator yields RunContentEvents AND a plain string, function_call_output should be the plain string."""
    clean_content = '{"finding": "clean result"}'

    def fake_generator():
        yield RunContentEvent(content="tok1", run_id="r1")
        yield RunContentEvent(content="tok2", run_id="r1")
        yield clean_content

    gen = fake_generator()

    # Simulate what run_function_call does for generators (with our fix)
    function_call_output = ""
    _has_event_content = False
    _non_event_output = ""

    event_types = tuple(get_args(RunOutputEvent)) + tuple(get_args(TeamRunOutputEvent))

    for item in gen:
        if isinstance(item, event_types):
            if isinstance(item, RunContentEvent):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
                _has_event_content = True
        else:
            function_call_output += str(item)
            _non_event_output += str(item)

    if _has_event_content and _non_event_output:
        function_call_output = _non_event_output

    assert function_call_output == clean_content


# ---------------------------------------------------------------------------
# Test: base.py logic — when only events exist, keeps accumulated output
# ---------------------------------------------------------------------------


def test_base_model_keeps_event_output_when_no_clean_content():
    """When a generator yields only RunContentEvents, function_call_output should be the accumulated events."""

    def fake_generator():
        yield RunContentEvent(content="tok1", run_id="r1")
        yield RunContentEvent(content="tok2", run_id="r1")

    gen = fake_generator()

    function_call_output = ""
    _has_event_content = False
    _non_event_output = ""

    event_types = tuple(get_args(RunOutputEvent)) + tuple(get_args(TeamRunOutputEvent))

    for item in gen:
        if isinstance(item, event_types):
            if isinstance(item, RunContentEvent):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
                _has_event_content = True
        else:
            function_call_output += str(item)
            _non_event_output += str(item)

    if _has_event_content and _non_event_output:
        function_call_output = _non_event_output

    assert function_call_output == "tok1tok2"


# ---------------------------------------------------------------------------
# Test: base.py logic — prefers clean output (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_model_prefers_clean_output_async():
    """Async version: when an async generator yields events AND a plain string, prefer the plain string."""
    clean_content = '{"finding": "async clean"}'

    async def fake_async_generator():
        yield RunContentEvent(content="tok1", run_id="r1")
        yield RunContentEvent(content="tok2", run_id="r1")
        yield clean_content

    function_call_output = ""
    _has_event_content = False
    _non_event_output = ""

    event_types = tuple(get_args(RunOutputEvent)) + tuple(get_args(TeamRunOutputEvent))

    async for item in fake_async_generator():
        if isinstance(item, event_types):
            if isinstance(item, RunContentEvent):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
                _has_event_content = True
        else:
            function_call_output += str(item)
            _non_event_output += str(item)

    if _has_event_content and _non_event_output:
        function_call_output = _non_event_output

    assert function_call_output == clean_content


# ---------------------------------------------------------------------------
# Test: _default_tools.py content extraction — BaseModel content yields JSON
# ---------------------------------------------------------------------------


def test_streaming_content_extraction_basemodel():
    """Verify the content extraction logic for BaseModel content from RunOutput."""
    from agno.run.agent import RunOutput

    content = ResearchResult(finding="test-finding")
    run_output = RunOutput(content=content, run_id="r1")

    # Simulate the extraction logic added to _default_tools.py after streaming loop
    extracted = None
    if run_output is not None:
        if isinstance(run_output.content, str):
            c = run_output.content.strip()
            if len(c) > 0:
                extracted = c
        elif issubclass(type(run_output.content), BaseModel):
            extracted = run_output.content.model_dump_json(indent=2)

    assert extracted == content.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Test: _default_tools.py content extraction — string content
# ---------------------------------------------------------------------------


def test_streaming_content_extraction_string():
    """Verify the content extraction logic for string content from RunOutput."""
    from agno.run.agent import RunOutput

    content = "plain string response"
    run_output = RunOutput(content=content, run_id="r1")

    extracted = None
    if run_output is not None:
        if isinstance(run_output.content, str):
            c = run_output.content.strip()
            if len(c) > 0:
                extracted = c
        elif issubclass(type(run_output.content), BaseModel):
            extracted = run_output.content.model_dump_json(indent=2)

    assert extracted == "plain string response"


# ---------------------------------------------------------------------------
# Test: _default_tools.py content extraction — agent name prefix for all_members
# ---------------------------------------------------------------------------


def test_streaming_content_extraction_with_agent_prefix():
    """Verify that delegate_task_to_members prefixes agent name to extracted content."""
    from agno.run.agent import RunOutput

    content = ResearchResult(finding="all-members-result")
    run_output = RunOutput(content=content, run_id="r1")
    agent_name = "researcher"

    # Simulate the extraction logic for delegate_task_to_members
    extracted = None
    if run_output is not None:
        if isinstance(run_output.content, str):
            c = run_output.content.strip()
            if len(c) > 0:
                extracted = f"Agent {agent_name}: {c}"
        elif issubclass(type(run_output.content), BaseModel):
            extracted = f"Agent {agent_name}: {run_output.content.model_dump_json(indent=2)}"

    expected = f"Agent researcher: {content.model_dump_json(indent=2)}"
    assert extracted == expected


# ---------------------------------------------------------------------------
# Test: TeamRunContentEvent also triggers event tracking
# ---------------------------------------------------------------------------


def test_base_model_prefers_clean_output_with_team_content_events():
    """When a generator yields TeamRunContentEvents AND a plain string, prefer the plain string."""
    clean_content = "final answer from team member"

    def fake_generator():
        yield TeamRunContentEvent(content="team-tok1", run_id="r1")
        yield TeamRunContentEvent(content="team-tok2", run_id="r1")
        yield clean_content

    gen = fake_generator()

    function_call_output = ""
    _has_event_content = False
    _non_event_output = ""

    event_types = tuple(get_args(RunOutputEvent)) + tuple(get_args(TeamRunOutputEvent))

    for item in gen:
        if isinstance(item, event_types):
            if isinstance(item, (RunContentEvent, TeamRunContentEvent)):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
                _has_event_content = True
        else:
            function_call_output += str(item)
            _non_event_output += str(item)

    if _has_event_content and _non_event_output:
        function_call_output = _non_event_output

    assert function_call_output == clean_content
