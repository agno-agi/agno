"""Regression tests for Team get_response_format resolution.

Team has no structured_outputs flag, so with a json_schema-only model
(LMStudio pre-flip, Perplexity, Cerebras) the DEFAULT configuration resolved
to None: no response_format reached the provider and structured output failed
silently.
"""

from pydantic import BaseModel

from agno.models.lmstudio import LMStudio
from agno.models.perplexity import Perplexity
from agno.run import RunContext
from agno.team import Team
from agno.team._response import get_response_format


class MovieScript(BaseModel):
    title: str
    rating: int


def _run_context():
    return RunContext(run_id="test-run", session_id="test-session", output_schema=MovieScript)


def _expected_json_schema():
    return {
        "type": "json_schema",
        "json_schema": {"name": "MovieScript", "schema": MovieScript.model_json_schema()},
    }


def test_team_defaults_regression():
    """The default Team configuration must resolve to a json_schema response_format."""
    team = Team(members=[], model=Perplexity())
    response_format = get_response_format(team, run_context=_run_context())
    assert response_format is not None
    assert response_format == _expected_json_schema()


def test_team_use_json_mode_unchanged():
    team = Team(members=[], model=Perplexity(), use_json_mode=True)
    assert get_response_format(team, run_context=_run_context()) == _expected_json_schema()


def test_team_lmstudio_defaults_use_native_path():
    team = Team(members=[], model=LMStudio())
    assert get_response_format(team, run_context=_run_context()) is MovieScript


def test_team_lmstudio_json_mode_returns_json_object():
    team = Team(members=[], model=LMStudio(), use_json_mode=True)
    assert get_response_format(team, run_context=_run_context()) == {"type": "json_object"}
