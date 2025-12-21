from unittest.mock import MagicMock, patch

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
