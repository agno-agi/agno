"""Unit tests for NanoBananaTools (agno.tools.nano_banana)."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("google.genai")
pytest.importorskip("PIL")

from agno.tools.nano_banana import NanoBananaTools  # noqa: E402


def test_default_model_is_current():
    """The default must be a model the Gemini API still serves (gemini-2.5-flash-image was shut down on Oct 2, 2026)."""
    tools = NanoBananaTools(api_key="test-key")
    assert tools.model == "gemini-3.1-flash-image"


def test_shut_down_model_is_rejected_up_front():
    """Asking for the shut-down model fails with a clear error instead of an API error at call time."""
    with pytest.raises(ValueError, match="gemini-3.1-flash-image"):
        NanoBananaTools(model="gemini-2.5-flash-image", api_key="test-key")


def test_create_image_sends_the_default_model():
    """create_image passes the configured model to generate_content."""
    tools = NanoBananaTools(api_key="test-key")
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = MagicMock(candidates=[])
    with patch("agno.tools.nano_banana.genai.Client", return_value=fake_client):
        tools.create_image("a yak")
    assert fake_client.models.generate_content.call_args.kwargs["model"] == "gemini-3.1-flash-image"
