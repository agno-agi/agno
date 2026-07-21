"""Regression tests for strict tool mode vs. parser_model in team _determine_tools_for_model.

When a parser_model is set, the base model does not produce the structured output
(the tool-less parser_model does), so the base model's tools must not be marked strict.
Forcing strict tools makes providers compile a grammar over every tool schema, which can
exceed provider limits (e.g. Anthropic: "the compiled grammar is too large").

Mirrors libs/agno/tests/unit/agent/test_parser_model_tool_strictness.py for Team.
"""

from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team


class _Output(BaseModel):
    summary: str


def _native_structured_model():
    model = MagicMock()
    model.supports_native_structured_outputs = True
    return model


def _sample_tool(query: str) -> str:
    """A sample tool."""
    return "ok"


def _run_context() -> RunContext:
    return RunContext(run_id="test-run", session_id="test-session", output_schema=_Output)


def _session() -> TeamSession:
    return TeamSession(session_id="test-session")


def _run_response() -> TeamRunOutput:
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _resolve_tools(team: Team):
    return _determine_tools_for_model(
        team=team,
        model=_native_structured_model(),
        run_response=_run_response(),
        run_context=_run_context(),
        team_run_context={},
        session=_session(),
        async_mode=False,
    )


def test_team_tools_strict_with_output_schema_and_no_parser_model():
    """Base model owns the structured output, so its tools are marked strict."""
    team = Team(name="t", members=[], tools=[_sample_tool])

    functions = _resolve_tools(team)

    assert len(functions) == 1
    assert functions[0].strict is True


def test_team_tools_not_strict_when_parser_model_is_set():
    """parser_model owns the structured output, so base model tools must not be strict."""
    team = Team(name="t", members=[], tools=[_sample_tool])
    team.parser_model = _native_structured_model()

    functions = _resolve_tools(team)

    assert len(functions) == 1
    assert not functions[0].strict
