import pytest

pytest.importorskip("openai")

from agno.models.llmman import Llmman
from agno.models.utils import get_model


def test_defaults():
    """llmman serves on its own port and takes a bare model reference."""
    model = Llmman()
    assert model.id == "qwen3:0.6b-q4_K_M"
    assert model.name == "Llmman"
    assert model.provider == "Llmman"
    assert model.base_url == "http://127.0.0.1:17434/v1"
    assert model.supports_native_structured_outputs is False
    assert model.supports_json_schema_outputs is True


def test_get_model_from_string():
    """The model id comes from the string without disturbing the base url."""
    model = get_model("llmman:qwen3.5:0.8B")
    assert isinstance(model, Llmman)
    assert model.id == "qwen3.5:0.8B"
    assert model.base_url == "http://127.0.0.1:17434/v1"
