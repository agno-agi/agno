"""Unit tests for DeepLTools class."""

import json
from unittest.mock import patch

import pytest

from agno.tools.deepl import DeepLTools


@pytest.fixture
def deepl_tools():
    """Fixture to create a DeepLTools instance with a mock API key."""
    return DeepLTools(api_key="test-api-key")


@pytest.fixture
def deepl_tools_free():
    """Fixture to create a DeepLTools instance with a free API key."""
    return DeepLTools(api_key="test-api-key:fx")


def test_toolkit_registration(deepl_tools):
    """Test that tools are registered correctly."""
    function_names = [func.name for func in deepl_tools.functions.values()]
    assert "translate_text" in function_names
    assert "get_supported_languages" in function_names


def test_toolkit_registration_all_tools():
    """Test that all tools are registered when all=True."""
    tools = DeepLTools(api_key="test-key", all=True)
    function_names = [func.name for func in tools.functions.values()]
    assert "translate_text" in function_names
    assert "get_supported_languages" in function_names
    assert "get_usage" in function_names


def test_free_api_url(deepl_tools_free):
    """Test that free API keys use the free API URL."""
    assert deepl_tools_free.base_url == "https://api-free.deepl.com"


def test_pro_api_url(deepl_tools):
    """Test that pro API keys use the pro API URL."""
    assert deepl_tools.base_url == "https://api.deepl.com"


def test_translate_text_success(deepl_tools):
    """Test successful translation."""
    mock_response = {
        "translations": [
            {
                "detected_source_language": "EN",
                "text": "Hallo, Welt!",
            }
        ]
    }

    with patch.object(deepl_tools, "_make_request", return_value=mock_response) as mock_request:
        result = deepl_tools.translate_text("Hello, world!", "DE")

    result_dict = json.loads(result)
    assert result_dict["detected_source_language"] == "EN"
    assert result_dict["text"] == "Hallo, Welt!"
    mock_request.assert_called_once()


def test_translate_text_with_options(deepl_tools):
    """Test translation with source language and formality options."""
    mock_response = {
        "translations": [
            {
                "detected_source_language": "EN",
                "text": "Können Sie mir helfen?",
            }
        ]
    }

    with patch.object(deepl_tools, "_make_request", return_value=mock_response) as mock_request:
        result = deepl_tools.translate_text(
            "Can you help me?",
            target_lang="DE",
            source_lang="EN",
            formality="more",
        )

    result_dict = json.loads(result)
    assert result_dict["text"] == "Können Sie mir helfen?"

    # Verify the request was made with correct parameters
    call_args = mock_request.call_args
    assert call_args[1]["data"]["source_lang"] == "EN"
    assert call_args[1]["data"]["formality"] == "more"


def test_translate_text_missing_api_key():
    """Test translation fails gracefully without API key."""
    tools = DeepLTools(api_key=None)
    # Clear the API key that might be set from environment
    tools.api_key = None

    result = tools.translate_text("Hello", "DE")
    assert "Error" in result
    assert "API key" in result


def test_translate_text_missing_text(deepl_tools):
    """Test translation fails gracefully with empty text."""
    result = deepl_tools.translate_text("", "DE")
    assert "Error" in result


def test_translate_text_missing_target_lang(deepl_tools):
    """Test translation fails gracefully without target language."""
    result = deepl_tools.translate_text("Hello", "")
    assert "Error" in result


def test_get_supported_languages_success(deepl_tools):
    """Test successful retrieval of supported languages."""
    mock_response = [
        {"language": "DE", "name": "German", "supports_formality": True},
        {"language": "FR", "name": "French", "supports_formality": True},
        {"language": "ES", "name": "Spanish", "supports_formality": True},
    ]

    with patch.object(deepl_tools, "_make_request", return_value=mock_response) as mock_request:
        result = deepl_tools.get_supported_languages("target")

    result_dict = json.loads(result)
    assert len(result_dict["languages"]) == 3
    assert result_dict["languages"][0]["code"] == "DE"
    assert result_dict["languages"][0]["supports_formality"] is True
    mock_request.assert_called_once_with("/v2/languages", params={"type": "target"})


def test_get_usage_success(deepl_tools):
    """Test successful retrieval of usage statistics."""
    mock_response = {
        "character_count": 50000,
        "character_limit": 500000,
    }

    # Enable get_usage tool for this test
    deepl_tools_with_usage = DeepLTools(api_key="test-key", enable_get_usage=True)

    with patch.object(deepl_tools_with_usage, "_make_request", return_value=mock_response):
        result = deepl_tools_with_usage.get_usage()

    result_dict = json.loads(result)
    assert result_dict["character_count"] == 50000
    assert result_dict["character_limit"] == 500000
    assert result_dict["percentage_used"] == 10.0


def test_translate_text_api_error(deepl_tools):
    """Test translation handles API errors gracefully."""
    with patch.object(deepl_tools, "_make_request", side_effect=Exception("API Error")):
        result = deepl_tools.translate_text("Hello", "DE")

    assert "Error" in result
    assert "API Error" in result
