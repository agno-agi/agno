from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.daoxe import DaoXE


def test_default_config():
    """Default DaoXE configuration points at the public Chat Completions base URL."""
    with patch.dict("os.environ", {}, clear=True):
        model = DaoXE(id="account-model-id", api_key="test-key")

    assert model.id == "account-model-id"
    assert model.name == "DaoXE"
    assert model.provider == "DaoXE"
    assert model.base_url == "https://daoxe.com/v1"
    assert model.api_key == "test-key"


def test_reads_env_defaults():
    """id and api_key fall back to DAOXE_MODEL / DAOXE_API_KEY when unset."""
    with patch.dict(
        "os.environ",
        {"DAOXE_MODEL": "env-model-id", "DAOXE_API_KEY": "env-key"},
        clear=True,
    ):
        model = DaoXE()

    assert model.id == "env-model-id"
    assert model.api_key == "env-key"


def test_requires_api_key():
    """DaoXE raises when no API key is available."""
    with patch.dict("os.environ", {}, clear=True):
        model = DaoXE(id="account-model-id", api_key=None)
        with pytest.raises(ModelAuthenticationError, match="DAOXE_API_KEY not set"):
            model._get_client_params()
