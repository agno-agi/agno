# test

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from agno.agent import Agent
from agno.media import ImageArtifact, VideoArtifact
from agno.tools.models.gemini import GeminiTools


# Fixture for mock agent
@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.add_image = MagicMock()
    return agent


# Fixture for mock client
@pytest.fixture
def mock_client():
    client = MagicMock()
    return client


# Fixture for mock GeminiTools with mock client
@pytest.fixture
def mock_gemini_tools(mock_client):
    def mock_getenv_side_effect(var_name):
        if var_name == "GOOGLE_GENAI_USE_VERTEXAI":
            return None
        return None

    with patch("agno.tools.models.gemini.Client", return_value=mock_client) as _, patch(
        "agno.tools.models.gemini.getenv", side_effect=mock_getenv_side_effect
    ) as _:
        gemini_tools = GeminiTools(api_key="fake_test_key")
        gemini_tools.client = mock_client
        return gemini_tools


# Fixture for successful API response
@pytest.fixture
def mock_successful_response():
    mock_response = MagicMock()
    mock_image = MagicMock()
    mock_image.image_bytes = b"fake_image_bytes"
    mock_response.generated_images = [MagicMock(image=mock_image)]
    return mock_response


# Fixture for failed API response (no image bytes)
@pytest.fixture
def mock_failed_response_no_bytes():
    mock_response = MagicMock()
    mock_response.generated_images = []  # Empty list to simulate no images generated
    return mock_response


# Test Initialization
def test_gemini_tools_init_with_api_key_arg():
    """Test initialization with API key provided as an argument."""
    api_key = "test_api_key_arg"

    def mock_getenv_side_effect(var_name):
        if var_name == "GOOGLE_GENAI_USE_VERTEXAI":
            return None
        return None

    with patch("agno.tools.models.gemini.Client") as mock_client_cls, patch(
        "agno.tools.models.gemini.getenv", side_effect=mock_getenv_side_effect
    ) as _:
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        gemini_tools = GeminiTools(api_key=api_key)

        assert gemini_tools.api_key == api_key
        mock_client_cls.assert_called_once_with(api_key=api_key)
        assert gemini_tools.client == mock_client_instance


def test_gemini_tools_init_with_env_var():
    """Test initialization with API key from environment variable."""
    env_api_key = "test_api_key_env"

    def mock_getenv_side_effect(var_name):
        if var_name == "GOOGLE_API_KEY":
            return env_api_key
        if var_name == "GOOGLE_GENAI_USE_VERTEXAI":
            return None
        return None

    with patch("agno.tools.models.gemini.getenv", side_effect=mock_getenv_side_effect) as mock_getenv:
        with patch("agno.tools.models.gemini.Client") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            gemini_tools = GeminiTools()

            assert gemini_tools.api_key == env_api_key
            mock_client_cls.assert_called_once_with(api_key=env_api_key)
            assert gemini_tools.client == mock_client_instance
            assert mock_getenv.call_count == 2


def test_gemini_tools_init_no_api_key():
    """Test initialization raises ValueError when no API key is found."""

    def mock_getenv_side_effect(var_name):
        return None

    with patch("agno.tools.models.gemini.getenv", side_effect=mock_getenv_side_effect) as mock_getenv:
        with pytest.raises(ValueError, match="GOOGLE_API_KEY not set"):
            GeminiTools()

        assert mock_getenv.call_count == 2


def test_gemini_tools_init_client_creation_fails():
    """Test initialization raises ValueError if Client creation fails."""
    with patch("agno.tools.models.gemini.getenv", return_value="fake_key") as _:
        with patch("agno.tools.models.gemini.Client") as mock_client_cls:
            mock_client_cls.side_effect = Exception("Client creation failed")

            with pytest.raises(ValueError, match="Failed to create Google GenAI Client"):
                GeminiTools()

            mock_client_cls.assert_called_once_with(api_key="fake_key")


# Test generate_image method
def test_generate_image_success(mock_gemini_tools, mock_agent, mock_successful_response):
    """Test successful image generation."""
    mock_gemini_tools.client.models.generate_images.return_value = mock_successful_response

    with patch("agno.tools.models.gemini.uuid4", return_value=UUID("12345678-1234-5678-1234-567812345678")):
        prompt = "A picture of a cat"
        image_model = "imagen-test-model"
        mock_gemini_tools.image_model = image_model  # Override default for test

        result = mock_gemini_tools.generate_image(mock_agent, prompt)

        expected_media_id = "12345678-1234-5678-1234-567812345678"
        assert result == "Image generated successfully"
        mock_gemini_tools.client.models.generate_images.assert_called_once_with(model=image_model, prompt=prompt)

        # Verify agent.add_image was called with the correct ImageArtifact
        mock_agent.add_image.assert_called_once()
        call_args, _ = mock_agent.add_image.call_args
        added_artifact = call_args[0]

        assert isinstance(added_artifact, ImageArtifact)
        assert added_artifact.id == expected_media_id
        assert added_artifact.original_prompt == prompt
        assert added_artifact.mime_type == "image/png"
        # Check if content is base64 encoded version of "fake_image_bytes"
        import base64

        expected_base64_bytes = base64.b64encode(b"fake_image_bytes")  # Keep as bytes
        assert added_artifact.content == expected_base64_bytes  # Compare bytes


def test_generate_image_api_error(mock_gemini_tools, mock_agent):
    """Test image generation when the API call raises an exception."""
    api_error_message = "API unavailable"
    mock_gemini_tools.client.models.generate_images.side_effect = Exception(api_error_message)

    prompt = "A picture of a dog"

    result = mock_gemini_tools.generate_image(mock_agent, prompt)

    expected_error = f"Failed to generate image: Client or method not available ({api_error_message})"
    assert result == expected_error
    mock_gemini_tools.client.models.generate_images.assert_called_once_with(
        model=mock_gemini_tools.image_model,  # Use default model
        prompt=prompt,
    )
    mock_agent.add_image.assert_not_called()


def test_generate_image_no_image_bytes(mock_gemini_tools, mock_agent, mock_failed_response_no_bytes):
    """Test image generation when the API response lacks image bytes."""
    mock_gemini_tools.client.models.generate_images.return_value = mock_failed_response_no_bytes

    prompt = "A picture of a bird"

    result = mock_gemini_tools.generate_image(mock_agent, prompt)

    assert result == "Failed to generate image: No images were generated."
    mock_gemini_tools.client.models.generate_images.assert_called_once_with(
        model=mock_gemini_tools.image_model,
        prompt=prompt,
    )
    mock_agent.add_image.assert_not_called()


# Tests for generate_video method
def test_generate_video_requires_vertexai(mock_gemini_tools, mock_agent):
    """Test video generation when vertexai mode is disabled."""
    mock_gemini_tools.vertexai = False  # Explicitly set vertexai to False
    prompt = "A sample video prompt"
    result = mock_gemini_tools.generate_video(mock_agent, prompt)
    expected = (
        "Video generation requires Vertex AI mode. "
        "Please set `vertexai=True` or environment variable `GOOGLE_GENAI_USE_VERTEXAI=true`."
    )
    assert result == expected
    mock_agent.add_video.assert_not_called()


@pytest.fixture
def mock_video_operation():
    """Fixture for a completed video generation operation."""
    op = MagicMock()
    op.done = True
    video = MagicMock()
    video.video_bytes = b"fake_video_bytes"
    video.mime_type = "video/mp4"
    op.result = MagicMock(generated_videos=[MagicMock(video=video)])
    return op


def test_generate_video_success(mock_gemini_tools, mock_agent, mock_video_operation):
    """Test successful video generation."""
    mock_gemini_tools.vertexai = True
    mock_gemini_tools.client.models.generate_videos.return_value = mock_video_operation
    prompt = "A sample video prompt"
    with patch("agno.tools.models.gemini.uuid4", return_value=UUID("87654321-4321-8765-4321-876543214321")):
        result = mock_gemini_tools.generate_video(mock_agent, prompt)
        expected_id = "87654321-4321-8765-4321-876543214321"
        assert result == "Video generated successfully"
        assert mock_gemini_tools.client.models.generate_videos.called
        call_args = mock_gemini_tools.client.models.generate_videos.call_args
        assert call_args.kwargs["model"] == mock_gemini_tools.video_model
        assert call_args.kwargs["prompt"] == prompt
        mock_agent.add_video.assert_called_once()
        added = mock_agent.add_video.call_args[0][0]
        assert isinstance(added, VideoArtifact)
        assert added.id == expected_id
        assert added.original_prompt == prompt
        assert added.mime_type == "video/mp4"
        import base64

        expected_content = base64.b64encode(b"fake_video_bytes").decode("utf-8")
        assert added.content == expected_content


def test_generate_video_exception(mock_gemini_tools, mock_agent):
    """Test video generation when API raises exception."""
    mock_gemini_tools.vertexai = True
    mock_gemini_tools.client.models.generate_videos.side_effect = Exception("API error")
    prompt = "A sample video prompt"
    result = mock_gemini_tools.generate_video(mock_agent, prompt)
    assert result == "Failed to generate video: API error"
    mock_agent.add_video.assert_not_called()
