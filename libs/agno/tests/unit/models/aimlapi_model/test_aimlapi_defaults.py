"""Tests for the AI/ML API model defaults."""

from agno.models.aimlapi import AIMLAPI


def test_default_model_id():
    """The default id is the bare alias AI/ML API publishes for GPT-5.6 Terra."""
    assert AIMLAPI(api_key="test-key").id == "gpt-5.6-terra"


def test_explicit_id_is_not_overridden():
    """Passing an id still wins over the default."""
    assert AIMLAPI(id="gpt-5.6-luna", api_key="test-key").id == "gpt-5.6-luna"
