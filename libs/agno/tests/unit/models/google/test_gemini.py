from unittest.mock import MagicMock, patch

import pytest

from agno.models.google.gemini import Gemini


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


def test_parallel_search_requires_api_key():
    """Test that parallel_search raises an error when no API key is provided."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        # No parallel_api_key provided and no env var
    )

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="parallel_api_key must be provided"):
            model.get_request_params()


def test_parallel_search_config():
    """Test that parallel_search is correctly configured in request params."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-parallel-key",
        parallel_endpoint="https://custom.parallel.ai/search",
    )

    with patch("agno.models.google.gemini.genai.Client"):
        request_params = model.get_request_params()

    # Verify config has tools
    assert "config" in request_params
    config = request_params["config"]

    # Verify tools are set
    assert hasattr(config, "tools") and config.tools is not None
    assert len(config.tools) == 1

    # Verify the tool is configured correctly
    tool = config.tools[0]
    assert tool.retrieval is not None
    assert tool.retrieval.external_api is not None
    assert tool.retrieval.external_api.api_spec == "SIMPLE_SEARCH"
    assert tool.retrieval.external_api.endpoint == "https://custom.parallel.ai/search"
    assert tool.retrieval.external_api.api_auth == {"apiKeyConfig": {"apiKeyString": "test-parallel-key"}}


def test_parallel_search_default_endpoint():
    """Test that parallel_search uses default endpoint when not specified."""
    model = Gemini(
        vertexai=True,
        project_id="test-project",
        location="test-location",
        parallel_search=True,
        parallel_api_key="test-parallel-key",
    )

    with patch("agno.models.google.gemini.genai.Client"):
        request_params = model.get_request_params()

    config = request_params["config"]
    tool = config.tools[0]
    assert tool.retrieval.external_api.endpoint == "https://api.parallel.ai/v1/search"


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
    tool = config.tools[0]
    assert tool.retrieval.external_api.api_auth == {"apiKeyConfig": {"apiKeyString": "env-parallel-key"}}
