import pytest

pytest.importorskip("openai")

from agno.models.hubris import Hubris
from agno.models.utils import get_model


def test_defaults():
    """Hubris points at the gateway and defaults to a catalog model id."""
    model = Hubris()
    assert model.id == "anthropic/claude-sonnet-5"
    assert model.name == "Hubris"
    assert model.provider == "Hubris"
    assert model.base_url == "https://api.hubris.pw/v1"


def test_get_model_from_string():
    """The vendor/model id survives the provider-prefixed string syntax."""
    model = get_model("hubris:openai/gpt-5.6-luna")
    assert isinstance(model, Hubris)
    assert model.id == "openai/gpt-5.6-luna"
    assert model.base_url == "https://api.hubris.pw/v1"


def test_missing_api_key_raises(monkeypatch):
    """Without a key the client refuses to start instead of sending an unauthenticated request."""
    from agno.exceptions import ModelAuthenticationError

    monkeypatch.delenv("HUBRIS_API_KEY", raising=False)
    with pytest.raises(ModelAuthenticationError):
        Hubris()._get_client_params()


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("HUBRIS_API_KEY", "sk-gw-test")
    model = Hubris()
    params = model._get_client_params()
    assert params["api_key"] == "sk-gw-test"
    assert params["base_url"] == "https://api.hubris.pw/v1"
