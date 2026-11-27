"""Regression tests for get_response_format resolution.

Models with supports_native_structured_outputs=False and
supports_json_schema_outputs=True must always receive a response_format when
an output_schema is set, across every use_json_mode and structured_outputs
combination. Cerebras shares Perplexity's exact flag combination but requires
cerebras-cloud-sdk to import, so Perplexity stands in for all
json_schema-only models here.
"""

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.agent._response import get_response_format
from agno.models.lmstudio import LMStudio
from agno.models.perplexity import Perplexity
from agno.run import RunContext


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


# =============================================================================
# json_schema-only models (Perplexity; same flags as LMStudio pre-flip, Cerebras)
# =============================================================================


@pytest.mark.parametrize("use_json_mode", [False, True])
@pytest.mark.parametrize("structured_outputs", [None, True])
def test_json_schema_only_model_always_receives_schema(use_json_mode, structured_outputs):
    agent = Agent(model=Perplexity(), use_json_mode=use_json_mode, structured_outputs=structured_outputs)
    assert get_response_format(agent, run_context=_run_context()) == _expected_json_schema()


def test_structured_outputs_true_regression():
    """structured_outputs=True with a json_schema-only model must resolve to a json_schema format."""
    agent = Agent(model=Perplexity(), structured_outputs=True)
    response_format = get_response_format(agent, run_context=_run_context())
    assert response_format is not None
    assert response_format == _expected_json_schema()


def test_dict_output_schema_passed_through_unchanged():
    provider_format = {"type": "json_schema", "json_schema": {"name": "custom", "schema": {"type": "object"}}}
    agent = Agent(model=Perplexity(), structured_outputs=True)
    run_context = RunContext(run_id="test-run", session_id="test-session", output_schema=provider_format)
    assert get_response_format(agent, run_context=run_context) is provider_format


def test_no_output_schema_returns_none():
    agent = Agent(model=Perplexity())
    run_context = RunContext(run_id="test-run", session_id="test-session")
    assert get_response_format(agent, run_context=run_context) is None


# =============================================================================
# LMStudio after enabling native structured outputs
# =============================================================================


def test_lmstudio_supports_native_structured_outputs():
    model = LMStudio()
    assert model.supports_native_structured_outputs is True
    assert model.supports_json_schema_outputs is True


def test_lmstudio_defaults_use_native_path():
    agent = Agent(model=LMStudio())
    assert get_response_format(agent, run_context=_run_context()) is MovieScript


def test_lmstudio_structured_outputs_true_uses_native_path():
    agent = Agent(model=LMStudio(), structured_outputs=True)
    assert get_response_format(agent, run_context=_run_context()) is MovieScript


def test_lmstudio_json_mode_returns_json_object():
    agent = Agent(model=LMStudio(), use_json_mode=True)
    assert get_response_format(agent, run_context=_run_context()) == {"type": "json_object"}


def test_lmstudio_structured_outputs_overrides_json_mode():
    agent = Agent(model=LMStudio(), use_json_mode=True, structured_outputs=True)
    assert get_response_format(agent, run_context=_run_context()) is MovieScript
