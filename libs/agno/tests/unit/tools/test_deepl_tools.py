"""Unit tests for DeepLTools class."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.deepl import DeepLTools


@pytest.fixture
def mock_urlopen():
    """Create a mock urlopen."""
    with patch("agno.tools.deepl.urlopen") as mock:
        yield mock


@pytest.fixture
def deepl_tools():
    """Fixture to create a DeepLTools instance with a mock API key."""
    return DeepLTools(api_key="test-api-key")


@pytest.fixture
def deepl_tools_free():
    """Fixture to create a DeepLTools instance with a free API key."""
    return DeepLTools(api_key="test-api-key:fx")


@pytest.fixture
def deepl_tools_all():
    """Fixture to create a DeepLTools instance with all tools enabled."""
    return DeepLTools(api_key="test-api-key", all=True)


def create_mock_response(data):
    """Create a mock HTTP response."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode()
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    return mock_response


class TestDeepLToolsInit:
    """Tests for DeepLTools initialization."""

    def test_init_with_provided_api_key(self):
        """Test initialization with provided API key."""
        tools = DeepLTools(api_key="my-api-key")
        assert tools.api_key == "my-api-key"

    def test_init_with_env_api_key(self):
        """Test initialization with API key from environment."""
        with patch.dict("os.environ", {"DEEPL_API_KEY": "env-test-key"}):
            tools = DeepLTools()
            assert tools.api_key == "env-test-key"

    def test_init_without_api_key_logs_warning(self):
        """Test initialization without API key logs a warning."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("agno.tools.deepl.logger") as mock_logger:
                import os

                old_key = os.environ.pop("DEEPL_API_KEY", None)
                try:
                    tools = DeepLTools()
                    mock_logger.warning.assert_called_once()
                    assert tools.api_key is None
                finally:
                    if old_key:
                        os.environ["DEEPL_API_KEY"] = old_key

    def test_init_with_default_tools(self):
        """Test that default tools are registered correctly."""
        tools = DeepLTools(api_key="test-key")
        function_names = [func.name for func in tools.functions.values()]
        assert "translate_text" in function_names
        assert "get_supported_languages" in function_names
        # get_usage is disabled by default
        assert "get_usage" not in function_names

    def test_init_with_all_tools(self):
        """Test that all tools are registered when all=True."""
        tools = DeepLTools(api_key="test-key", all=True)
        function_names = [func.name for func in tools.functions.values()]
        assert "translate_text" in function_names
        assert "get_supported_languages" in function_names
        assert "get_usage" in function_names

    def test_init_with_selective_tools(self):
        """Test initialization with only selected tools."""
        tools = DeepLTools(
            api_key="test-key",
            enable_translate_text=True,
            enable_get_supported_languages=False,
            enable_get_usage=True,
        )
        function_names = [func.name for func in tools.functions.values()]
        assert "translate_text" in function_names
        assert "get_supported_languages" not in function_names
        assert "get_usage" in function_names

    def test_free_api_url(self, deepl_tools_free):
        """Test that free API keys use the free API URL."""
        assert deepl_tools_free.base_url == "https://api-free.deepl.com"

    def test_pro_api_url(self, deepl_tools):
        """Test that pro API keys use the pro API URL."""
        assert deepl_tools.base_url == "https://api.deepl.com"


class TestTranslateText:
    """Tests for translate_text method."""

    def test_translate_text_success(self, deepl_tools, mock_urlopen):
        """Test successful translation."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Hallo, Welt!",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text("Hello, world!", "DE")
        result_dict = json.loads(result)

        assert result_dict["detected_source_language"] == "EN"
        assert result_dict["text"] == "Hallo, Welt!"

    def test_translate_text_with_source_lang(self, deepl_tools, mock_urlopen):
        """Test translation with explicit source language."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Bonjour le monde!",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text("Hello, world!", "FR", source_lang="EN")
        result_dict = json.loads(result)

        assert result_dict["text"] == "Bonjour le monde!"

    def test_translate_text_with_formality(self, deepl_tools, mock_urlopen):
        """Test translation with formality option."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Können Sie mir helfen?",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text(
            "Can you help me?",
            target_lang="DE",
            formality="more",
        )
        result_dict = json.loads(result)

        assert result_dict["text"] == "Können Sie mir helfen?"

    def test_translate_text_with_context(self, deepl_tools, mock_urlopen):
        """Test translation with context for better accuracy."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Das Schloss war wunderschön.",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text(
            "The castle was beautiful.",
            target_lang="DE",
            context="We visited a medieval castle in Germany.",
        )
        result_dict = json.loads(result)

        assert result_dict["text"] == "Das Schloss war wunderschön."

    def test_translate_text_all_options(self, deepl_tools, mock_urlopen):
        """Test translation with all options."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Sehr geehrte Damen und Herren",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text(
            "Dear Sir or Madam",
            target_lang="DE",
            source_lang="EN",
            formality="more",
            context="This is a formal business letter.",
        )
        result_dict = json.loads(result)

        assert result_dict["detected_source_language"] == "EN"
        assert "geehrte" in result_dict["text"]

    def test_translate_text_without_api_key(self):
        """Test translation fails gracefully without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("DEEPL_API_KEY", None)
            try:
                tools = DeepLTools()
                result = tools.translate_text("Hello", "DE")
                assert "Error: No DeepL API key provided" in result
            finally:
                if old_key:
                    os.environ["DEEPL_API_KEY"] = old_key

    def test_translate_text_empty_text(self, deepl_tools):
        """Test translation fails gracefully with empty text."""
        result = deepl_tools.translate_text("", "DE")
        assert "Error: Please provide text to translate" in result

    def test_translate_text_empty_target_lang(self, deepl_tools):
        """Test translation fails gracefully without target language."""
        result = deepl_tools.translate_text("Hello", "")
        assert "Error: Please provide a target language code" in result

    def test_translate_text_api_error(self, deepl_tools, mock_urlopen):
        """Test translation handles API errors gracefully."""
        mock_urlopen.side_effect = Exception("API Connection Error")

        result = deepl_tools.translate_text("Hello", "DE")
        assert "Error translating text: API Connection Error" in result

    def test_translate_text_empty_translations(self, deepl_tools, mock_urlopen):
        """Test handling of empty translations response."""
        mock_response_data = {"translations": []}
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text("Hello", "DE")
        assert "Error: No translation returned from API" in result

    def test_translate_text_invalid_formality_ignored(self, deepl_tools, mock_urlopen):
        """Test that invalid formality values are ignored."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Hallo",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        # Invalid formality should be silently ignored
        result = deepl_tools.translate_text("Hello", "DE", formality="invalid_formality")
        result_dict = json.loads(result)
        assert result_dict["text"] == "Hallo"

    def test_translate_text_uppercase_conversion(self, deepl_tools, mock_urlopen):
        """Test that language codes are converted to uppercase."""
        mock_response_data = {
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Hallo",
                }
            ]
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        # Pass lowercase language codes
        result = deepl_tools.translate_text("Hello", "de", source_lang="en")
        result_dict = json.loads(result)
        assert result_dict["text"] == "Hallo"


class TestGetSupportedLanguages:
    """Tests for get_supported_languages method."""

    def test_get_supported_languages_target(self, deepl_tools, mock_urlopen):
        """Test successful retrieval of target languages."""
        mock_response_data = [
            {"language": "DE", "name": "German", "supports_formality": True},
            {"language": "FR", "name": "French", "supports_formality": True},
            {"language": "ES", "name": "Spanish", "supports_formality": True},
            {"language": "JA", "name": "Japanese", "supports_formality": False},
        ]
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.get_supported_languages("target")
        result_dict = json.loads(result)

        assert len(result_dict["languages"]) == 4
        assert result_dict["languages"][0]["code"] == "DE"
        assert result_dict["languages"][0]["name"] == "German"
        assert result_dict["languages"][0]["supports_formality"] is True
        assert result_dict["languages"][3]["supports_formality"] is False

    def test_get_supported_languages_source(self, deepl_tools, mock_urlopen):
        """Test retrieval of source languages."""
        mock_response_data = [
            {"language": "EN", "name": "English"},
            {"language": "DE", "name": "German"},
        ]
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.get_supported_languages("source")
        result_dict = json.loads(result)

        assert len(result_dict["languages"]) == 2
        # Languages without supports_formality should default to False
        assert result_dict["languages"][0]["supports_formality"] is False

    def test_get_supported_languages_default_type(self, deepl_tools, mock_urlopen):
        """Test default language type is 'target'."""
        mock_response_data = [{"language": "DE", "name": "German", "supports_formality": True}]
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.get_supported_languages()
        result_dict = json.loads(result)

        assert len(result_dict["languages"]) == 1

    def test_get_supported_languages_without_api_key(self):
        """Test get_supported_languages fails gracefully without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("DEEPL_API_KEY", None)
            try:
                tools = DeepLTools()
                result = tools.get_supported_languages()
                assert "Error: No DeepL API key provided" in result
            finally:
                if old_key:
                    os.environ["DEEPL_API_KEY"] = old_key

    def test_get_supported_languages_api_error(self, deepl_tools, mock_urlopen):
        """Test get_supported_languages handles API errors gracefully."""
        mock_urlopen.side_effect = Exception("API Error")

        result = deepl_tools.get_supported_languages()
        assert "Error getting supported languages: API Error" in result


class TestGetUsage:
    """Tests for get_usage method."""

    def test_get_usage_success(self, deepl_tools_all, mock_urlopen):
        """Test successful retrieval of usage statistics."""
        mock_response_data = {
            "character_count": 50000,
            "character_limit": 500000,
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools_all.get_usage()
        result_dict = json.loads(result)

        assert result_dict["character_count"] == 50000
        assert result_dict["character_limit"] == 500000
        assert result_dict["percentage_used"] == 10.0

    def test_get_usage_percentage_calculation(self, deepl_tools_all, mock_urlopen):
        """Test percentage calculation with various values."""
        mock_response_data = {
            "character_count": 123456,
            "character_limit": 500000,
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools_all.get_usage()
        result_dict = json.loads(result)

        # 123456 / 500000 * 100 = 24.6912
        assert result_dict["percentage_used"] == 24.69

    def test_get_usage_zero_count(self, deepl_tools_all, mock_urlopen):
        """Test usage with zero character count."""
        mock_response_data = {
            "character_count": 0,
            "character_limit": 500000,
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools_all.get_usage()
        result_dict = json.loads(result)

        assert result_dict["character_count"] == 0
        assert result_dict["percentage_used"] == 0.0

    def test_get_usage_without_api_key(self):
        """Test get_usage fails gracefully without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("DEEPL_API_KEY", None)
            try:
                tools = DeepLTools(enable_get_usage=True)
                result = tools.get_usage()
                assert "Error: No DeepL API key provided" in result
            finally:
                if old_key:
                    os.environ["DEEPL_API_KEY"] = old_key

    def test_get_usage_api_error(self, deepl_tools_all, mock_urlopen):
        """Test get_usage handles API errors gracefully."""
        mock_urlopen.side_effect = Exception("API Error")

        result = deepl_tools_all.get_usage()
        assert "Error getting usage: API Error" in result


class TestMakeRequest:
    """Tests for _make_request helper method."""

    def test_make_request_get_with_params(self, deepl_tools, mock_urlopen):
        """Test GET request includes query parameters."""
        mock_urlopen.return_value = create_mock_response({"test": "data"})

        deepl_tools._make_request("/v2/languages", params={"type": "target"})

        call_args = mock_urlopen.call_args[0][0]
        assert "/v2/languages?" in call_args.full_url
        assert "type=target" in call_args.full_url

    def test_make_request_post_with_data(self, deepl_tools, mock_urlopen):
        """Test POST request includes JSON body."""
        mock_urlopen.return_value = create_mock_response({"translations": []})

        deepl_tools._make_request(
            "/v2/translate",
            method="POST",
            data={"text": ["Hello"], "target_lang": "DE"},
        )

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.method == "POST"
        assert call_args.data is not None

    def test_make_request_includes_auth_header(self, deepl_tools, mock_urlopen):
        """Test request includes authorization header."""
        mock_urlopen.return_value = create_mock_response({"test": "data"})

        deepl_tools._make_request("/v2/usage")

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.headers["Authorization"] == "DeepL-Auth-Key test-api-key"
        assert call_args.headers["Content-type"] == "application/json"

    def test_make_request_uses_correct_base_url_pro(self, deepl_tools, mock_urlopen):
        """Test pro API uses correct base URL."""
        mock_urlopen.return_value = create_mock_response({})

        deepl_tools._make_request("/v2/usage")

        call_args = mock_urlopen.call_args[0][0]
        assert "api.deepl.com" in call_args.full_url
        assert "api-free" not in call_args.full_url

    def test_make_request_uses_correct_base_url_free(self, deepl_tools_free, mock_urlopen):
        """Test free API uses correct base URL."""
        mock_urlopen.return_value = create_mock_response({})

        deepl_tools_free._make_request("/v2/usage")

        call_args = mock_urlopen.call_args[0][0]
        assert "api-free.deepl.com" in call_args.full_url


class TestFormalityOptions:
    """Tests for formality option handling."""

    @pytest.mark.parametrize(
        "formality",
        ["default", "more", "less", "prefer_more", "prefer_less"],
    )
    def test_valid_formality_options(self, formality, deepl_tools, mock_urlopen):
        """Test all valid formality options are accepted."""
        mock_response_data = {"translations": [{"detected_source_language": "EN", "text": "Hallo"}]}
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = deepl_tools.translate_text("Hello", "DE", formality=formality)
        result_dict = json.loads(result)

        assert result_dict["text"] == "Hallo"
