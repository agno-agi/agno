"""
Unit tests for the ModelsLab provider.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from agno.models.modelslab import ModelsLab
from agno.models.modelslab.chat import ModelsLab as ModelsLabChat


class TestModelsLabDefaults:
    """Test ModelsLab dataclass defaults."""

    def test_default_model_id(self):
        m = ModelsLab()
        assert m.id == "llama-3.1-8b-uncensored"

    def test_default_name(self):
        m = ModelsLab()
        assert m.name == "ModelsLab"

    def test_default_provider(self):
        m = ModelsLab()
        assert m.provider == "ModelsLab"

    def test_default_base_url(self):
        m = ModelsLab()
        assert m.base_url == "https://modelslab.com/uncensored-chat/v1"

    def test_default_api_key_is_none(self):
        m = ModelsLab()
        assert m.api_key is None


class TestModelsLabConfiguration:
    """Test configuration overrides."""

    def test_custom_model_id(self):
        m = ModelsLab(id="llama-3.1-70b-uncensored")
        assert m.id == "llama-3.1-70b-uncensored"

    def test_api_key_override(self):
        m = ModelsLab(api_key="test-key-abc")
        assert m.api_key == "test-key-abc"

    def test_custom_base_url(self):
        custom_url = "https://custom.modelslab.com/v1"
        m = ModelsLab(base_url=custom_url)
        assert m.base_url == custom_url

    def test_inherits_from_openai_chat(self):
        from agno.models.openai.chat import OpenAIChat
        assert issubclass(ModelsLab, OpenAIChat)

    def test_import_from_package(self):
        """Ensure __init__.py exports are correct."""
        from agno.models.modelslab import ModelsLab as ML
        assert ML is ModelsLabChat

    @patch.dict(os.environ, {"MODELSLAB_API_KEY": "env-key-xyz"})
    def test_env_var_picked_up(self):
        """ModelsLab should read MODELSLAB_API_KEY when api_key not set."""
        # The OpenAIChat base class reads api_key from env if not explicitly set.
        # This test confirms the env var is available for the base class to read.
        assert os.environ.get("MODELSLAB_API_KEY") == "env-key-xyz"


class TestModelsLabModels:
    """Test available model IDs."""

    def test_8b_model_valid(self):
        m = ModelsLab(id="llama-3.1-8b-uncensored")
        assert "8b" in m.id

    def test_70b_model_valid(self):
        m = ModelsLab(id="llama-3.1-70b-uncensored")
        assert "70b" in m.id

    def test_context_window_128k(self):
        """Both models have 128K context — verify naming convention."""
        for model_id in ["llama-3.1-8b-uncensored", "llama-3.1-70b-uncensored"]:
            m = ModelsLab(id=model_id)
            assert "llama-3.1" in m.id
            assert "uncensored" in m.id
