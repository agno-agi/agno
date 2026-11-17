"""Unit tests for the Sambanova model defaults."""

from agno.models.sambanova import Sambanova


def test_default_model_id_is_supported():
    model = Sambanova(api_key="test-key")
    assert model.id == "Meta-Llama-3.3-70B-Instruct"
