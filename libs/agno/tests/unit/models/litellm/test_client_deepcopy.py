"""
Tests for LiteLLM client preservation across deepcopy.

This test verifies that custom client objects are preserved when the model is deep copied for background tasks.
"""

from copy import deepcopy
from unittest.mock import MagicMock

from agno.models.litellm import LiteLLM


def test_client_preserved_after_deepcopy():
    """Verify that client is preserved after deepcopy."""
    mock_client = MagicMock()
    model = LiteLLM(id="test-model", client=mock_client)

    model_copy = deepcopy(model)

    assert model_copy.client is mock_client


def test_original_client_set_on_init():
    """Verify that _original_client is set when client is provided."""
    mock_client = MagicMock()
    model = LiteLLM(id="test-model", client=mock_client)

    assert model._original_client is mock_client


def test_get_client_returns_client_after_deepcopy():
    """Verify that get_client() returns the client after deepcopy."""
    mock_client = MagicMock()
    model = LiteLLM(id="test-model", client=mock_client)

    model_copy = deepcopy(model)

    assert model_copy.get_client() is mock_client


def test_get_client_falls_back_to_original_client():
    """Verify that get_client() falls back to _original_client when client is None."""
    mock_client = MagicMock()
    model = LiteLLM(id="test-model", client=mock_client)

    model.client = None

    assert model.get_client() is mock_client
