import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agno.media import File
from agno.models.google.gemini import Gemini
from agno.models.message import Message


def test_gemini_get_client_with_credentials_vertexai():
    """Test that credentials are correctly passed to the client when vertexai is True."""
    mock_credentials = MagicMock()
    model = Gemini(vertexai=True, project_id="test-project", location="test-location", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were passed to the client
        _, kwargs = mock_client_cls.call_args
        assert kwargs["credentials"] == mock_credentials
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "test-project"
        assert kwargs["location"] == "test-location"


def test_gemini_get_client_without_credentials_vertexai():
    """Test that client is initialized without credentials when not provided in vertexai mode."""
    model = Gemini(vertexai=True, project_id="test-project", location="test-location")

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were NOT passed to the client
        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert kwargs["vertexai"] is True


def test_gemini_get_client_ai_studio_mode():
    """Test that credentials are NOT passed in Google AI Studio mode (non-vertexai)."""
    mock_credentials = MagicMock()
    # Even if credentials are provided, they shouldn't be passed if vertexai=False
    model = Gemini(vertexai=False, api_key="test-api-key", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were NOT passed to the client
        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert "api_key" in kwargs
        assert kwargs.get("vertexai") is not True


class TestFormatFileForMessage:
    def _make_model(self):
        model = Gemini(api_key="test-key")
        return model

    @patch("agno.models.google.gemini.Part")
    def test_bytes_with_mime_type(self, mock_part):
        model = self._make_model()
        f = File(content=b"hello", mime_type="text/plain")
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="text/plain", data=b"hello")

    @patch("agno.models.google.gemini.Part")
    def test_bytes_without_mime_type_guesses_from_filename(self, mock_part):
        model = self._make_model()
        f = File(content=b"data", filename="report.pdf")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"data")

    @patch("agno.models.google.gemini.Part")
    def test_bytes_without_mime_type_or_filename_falls_back(self, mock_part):
        model = self._make_model()
        f = File(content=b"data")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"data")

    @patch("agno.models.google.gemini.Part")
    def test_gcs_uri_without_mime_type(self, mock_part):
        model = self._make_model()
        f = File(url="gs://bucket/file.csv")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_uri.assert_called_once_with(file_uri="gs://bucket/file.csv", mime_type="text/csv")

    @patch("agno.models.google.gemini.Part")
    def test_https_url_with_mime_type_sends_as_uri(self, mock_part):
        model = self._make_model()
        f = File(url="https://example.com/report.pdf", mime_type="application/pdf")
        model._format_file_for_message(f)
        mock_part.from_uri.assert_called_once_with(
            file_uri="https://example.com/report.pdf", mime_type="application/pdf"
        )

    @patch("agno.models.google.gemini.Part")
    def test_https_url_without_mime_type_falls_through_to_download(self, mock_part):
        model = self._make_model()
        f = File(url="https://example.com/report.pdf")
        f.mime_type = None
        # Mock the download property to return content with detected MIME
        with patch.object(
            type(f), "file_url_content", new_callable=lambda: property(lambda self: (b"pdf-data", "application/pdf"))
        ):
            model._format_file_for_message(f)
        mock_part.from_uri.assert_not_called()
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"pdf-data")

    @patch("agno.models.google.gemini.Part")
    def test_local_file_without_mime_type(self, mock_part):
        model = self._make_model()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"hello world")
            tmp.flush()
            f = File(filepath=tmp.name)
            f.mime_type = None
            model._format_file_for_message(f)
            mock_part.from_bytes.assert_called_once_with(mime_type="text/plain", data=b"hello world")
            Path(tmp.name).unlink()

    @patch("agno.models.google.gemini.Part")
    def test_local_file_without_mime_type_or_extension_falls_back(self, mock_part):
        model = self._make_model()
        with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp:
            tmp.write(b"binary data")
            tmp.flush()
            f = File(filepath=tmp.name)
            f.mime_type = None
            model._format_file_for_message(f)
            mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"binary data")
            Path(tmp.name).unlink()


class TestFormatMessagesEmptyParts:
    """Test that messages with empty parts are filtered out before sending to Gemini API."""

    def _make_model(self):
        model = Gemini(api_key="test-key")
        return model

    def test_filters_message_with_none_content(self):
        """Messages with None content and no tool calls should be filtered out."""
        model = self._make_model()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content=None),  # empty parts
            Message(role="user", content="How are you?"),
        ]
        formatted, system_msg = model._format_messages(messages)
        # System message is extracted separately, not in formatted list.
        # The assistant message with None content is filtered out, and the two
        # consecutive user messages are merged into one (Gemini requires alternating roles).
        assert len(formatted) == 1
        assert len(formatted[0].parts) == 2
        assert all(msg.parts for msg in formatted)

    def test_filters_message_with_empty_list_content(self):
        """Messages with list content but no tool calls produce empty parts and should be filtered."""
        model = self._make_model()
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content=["some list"]),  # list content, no tool calls -> empty parts
            Message(role="user", content="Next question"),
        ]
        formatted, system_msg = model._format_messages(messages)
        # The assistant message with list content (no tool_calls) falls through
        # the text content branch without adding parts, so it should be filtered.
        # The two consecutive user messages are merged (Gemini requires alternating roles).
        assert len(formatted) == 1
        assert len(formatted[0].parts) == 2
        for msg in formatted:
            assert msg.parts is not None
            assert len(msg.parts) > 0

    def test_keeps_message_with_valid_content(self):
        """Messages with valid string content should be kept."""
        model = self._make_model()
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
            Message(role="user", content="Thanks"),
        ]
        formatted, system_msg = model._format_messages(messages)
        assert len(formatted) == 3
        for msg in formatted:
            assert msg.parts is not None
            assert len(msg.parts) > 0

    def test_keeps_system_message_separate(self):
        """System messages should be extracted as system_message, not in formatted list."""
        model = self._make_model()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="Hello"),
        ]
        formatted, system_msg = model._format_messages(messages)
        assert system_msg == "Be helpful"
        assert len(formatted) == 1

    def test_all_empty_parts_returns_empty_list(self):
        """If all non-system messages have empty parts, return empty formatted list."""
        model = self._make_model()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="assistant", content=None),
        ]
        formatted, system_msg = model._format_messages(messages)
        assert system_msg == "Be helpful"
        assert len(formatted) == 0

    def test_mixed_valid_and_empty_messages(self):
        """Only empty-parts messages are filtered; valid ones are kept and consecutive same-role merged."""
        model = self._make_model()
        messages = [
            Message(role="user", content="First"),
            Message(role="assistant", content=None),  # will be filtered
            Message(role="user", content="Second"),
            Message(role="assistant", content="Response"),
            Message(role="assistant", content=None),  # will be filtered
            Message(role="user", content="Third"),
        ]
        formatted, system_msg = model._format_messages(messages)
        # After filtering empty assistants: user("First"), user("Second"), model("Response"), user("Third")
        # After merging consecutive same-role: user("First"+"Second"), model("Response"), user("Third")
        assert len(formatted) == 3
        roles = [msg.role for msg in formatted]
        assert roles == ["user", "model", "user"]


class TestGeminiTimeout:
    """Test that the timeout parameter is correctly wired into the Gemini client."""

    def test_timeout_sets_http_options(self):
        """Test that timeout is converted to milliseconds and passed via http_options."""
        model = Gemini(api_key="test-key", timeout=30.0)

        with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
            model.get_client()

            _, kwargs = mock_client_cls.call_args
            assert "http_options" in kwargs
            assert kwargs["http_options"]["timeout"] == 30000

    def test_timeout_none_does_not_set_http_options(self):
        """Test that no http_options are added when timeout is None."""
        model = Gemini(api_key="test-key", timeout=None)

        with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
            model.get_client()

            _, kwargs = mock_client_cls.call_args
            assert "http_options" not in kwargs

    def test_timeout_fractional_seconds(self):
        """Test that fractional seconds are correctly converted to integer milliseconds."""
        model = Gemini(api_key="test-key", timeout=1.5)

        with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
            model.get_client()

            _, kwargs = mock_client_cls.call_args
            assert kwargs["http_options"]["timeout"] == 1500

    def test_timeout_does_not_override_client_params_http_options(self):
        """Test that client_params http_options take precedence over timeout."""
        model = Gemini(
            api_key="test-key",
            timeout=30.0,
            client_params={"http_options": {"timeout": 60000}},
        )

        with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
            model.get_client()

            _, kwargs = mock_client_cls.call_args
            # client_params is applied after timeout, so it should override
            assert kwargs["http_options"]["timeout"] == 60000

    def test_timeout_with_vertexai(self):
        """Test that timeout works correctly in Vertex AI mode."""
        model = Gemini(
            vertexai=True,
            project_id="test-project",
            location="test-location",
            timeout=10.0,
        )

        with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
            model.get_client()

            _, kwargs = mock_client_cls.call_args
            assert kwargs["http_options"]["timeout"] == 10000
            assert kwargs["vertexai"] is True


def test_parallel_search_requires_vertexai():
    """Test that parallel_search raises an error when vertexai is not enabled."""
    model = Gemini(
        vertexai=False,
        api_key="test-api-key",
        parallel_search=True,
        parallel_api_key="test-parallel-key",
    )

    with pytest.raises(ValueError, match="Parallel search grounding requires vertexai=True"):
        model.get_request_params()


def test_parallel_search_incompatible_with_google_search():
    """Test that parallel_search cannot be combined with google_search."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-key",
        search=True,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        with pytest.raises(ValueError, match="cannot be combined"):
            model.get_request_params()


def test_parallel_search_incompatible_with_grounding():
    """Test that parallel_search cannot be combined with grounding."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-key",
        grounding=True,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        with pytest.raises(ValueError, match="cannot be combined"):
            model.get_request_params()


def test_parallel_search_config_with_api_key():
    """Test that parallel_search is correctly configured with an explicit API key."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-parallel-key",
    )

    with patch("agno.models.google.gemini.genai.Client"):
        request_params = model.get_request_params()

    assert "config" in request_params
    config = request_params["config"]
    assert config.tools is not None
    assert len(config.tools) == 1
    tool = config.tools[0]
    assert tool.parallel_ai_search is not None
    assert tool.parallel_ai_search.api_key == "test-parallel-key"


def test_parallel_search_config_without_api_key():
    """Test that parallel_search works without an API key (GCP Marketplace subscription)."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        with patch.dict("os.environ", {}, clear=False):
            import os

            env_backup = os.environ.pop("PARALLEL_API_KEY", None)
            try:
                request_params = model.get_request_params()
            finally:
                if env_backup is not None:
                    os.environ["PARALLEL_API_KEY"] = env_backup

    config = request_params["config"]
    assert config.tools is not None
    assert len(config.tools) == 1
    tool = config.tools[0]
    assert tool.parallel_ai_search is not None
    assert tool.parallel_ai_search.api_key is None


def test_parallel_search_with_env_var():
    """Test that parallel_search can use PARALLEL_API_KEY from environment."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        with patch.dict("os.environ", {"PARALLEL_API_KEY": "env-parallel-key"}):
            request_params = model.get_request_params()

    config = request_params["config"]
    assert config.tools is not None
    tool = config.tools[0]
    assert tool.parallel_ai_search is not None
    assert tool.parallel_ai_search.api_key == "env-parallel-key"


def test_parallel_search_with_custom_config():
    """Test that parallel_config is passed as custom_configs in the tool payload."""
    custom_config = {"source_policy": {"exclude_domains": ["example.com"]}}
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-key",
        parallel_config=custom_config,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        request_params = model.get_request_params()

    config = request_params["config"]
    tool = config.tools[0]
    assert tool.parallel_ai_search is not None
    assert tool.parallel_ai_search.api_key == "test-key"
    assert tool.parallel_ai_search.custom_configs == custom_config


def test_parallel_search_with_other_builtin_tools():
    """Test that parallel_search can coexist with url_context."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-key",
        url_context=True,
    )

    with patch("agno.models.google.gemini.genai.Client"):
        request_params = model.get_request_params()

    config = request_params["config"]
    assert config.tools is not None
    assert len(config.tools) == 2
    tool_types = []
    for t in config.tools:
        if t.url_context is not None:
            tool_types.append("url_context")
        if t.parallel_ai_search is not None:
            tool_types.append("parallel_ai_search")
    assert "url_context" in tool_types
    assert "parallel_ai_search" in tool_types


def test_parallel_search_with_external_tools_logs_warning():
    """Test that parallel_search with external tools logs the builtin tools info."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-key",
    )

    with patch("agno.models.google.gemini.genai.Client"):
        with patch("agno.models.google.gemini.log_info") as mock_info:
            model.get_request_params(tools=[{"type": "function", "function": {"name": "test_fn"}}])
            mock_info.assert_called_once_with("Built-in tools enabled. External tools will be disabled.")
