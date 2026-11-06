"""Unit tests for the TogetherLink model class.

TogetherLink is an OpenAI-compatible gateway authenticated with a Together API key, so the
class is a thin OpenAILike subclass. These tests pin the defaults and the missing-key behavior
without any network access. (The to_dict/from_dict round-trip is covered generically by
``test_provider_resolution.py`` via the provider registry.)
"""

import pytest
from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.togetherlink import TogetherLink


def test_defaults():
    """Defaults match the TogetherLink OpenAI-compatible gateway."""
    model = TogetherLink(api_key="test-key")
    assert isinstance(model, OpenAILike)
    assert model.id == "auto"
    assert model.name == "TogetherLink"
    assert model.provider == "TogetherLink"
    assert model.base_url == "https://gateway.togetherlink.dev/v1"


def test_structured_outputs_use_json_mode():
    """output_schema goes through the system prompt plus json_object, not a bare json_schema response_format."""
    from agno.agent import Agent
    from agno.agent._response import get_response_format
    from agno.run import RunContext

    class City(BaseModel):
        name: str

    model = TogetherLink(api_key="test-key")
    agent = Agent(model=model, output_schema=City)
    run_context = RunContext(run_id="r", session_id="s", output_schema=City)

    assert model.supports_native_structured_outputs is False
    assert model.supports_json_schema_outputs is False
    assert get_response_format(agent, run_context=run_context) == {"type": "json_object"}


def test_api_key_from_env(monkeypatch):
    """The API key is read from TOGETHER_API_KEY when not passed explicitly."""
    monkeypatch.setenv("TOGETHER_API_KEY", "env-key")
    assert TogetherLink().api_key == "env-key"


def test_client_params_include_base_url():
    """Client params carry the configured key and base URL through to the SDK."""
    params = TogetherLink(id="zai-org/GLM-5.3-Flash", api_key="test-key")._get_client_params()
    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://gateway.togetherlink.dev/v1"


def test_missing_api_key_raises(monkeypatch):
    """A missing API key raises ModelAuthenticationError instead of falling back to OPENAI_API_KEY."""
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    with pytest.raises(ModelAuthenticationError):
        TogetherLink(api_key=None)._get_client_params()
