# test

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools.models.gemini import GeminiTools


# Fixture for mock agent
@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.add_image = MagicMock()
    return agent


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
    mock_image = MagicMock()
    # Simulate the case where image_bytes is None or missing
    mock_image.image_bytes = None
    mock_response.generated_images = [MagicMock(image=mock_image)]
    return mock_response


# Test Initialization
@patch("agno.tools.models.gemini.getenv")
@patch("agno.tools.models.gemini.Client")
def test_gemini_tools_init_with_api_key_arg(mock_client_cls, mock_getenv):
    """Test initialization with API key provided as an argument."""
    mock_client_instance = MagicMock()
    mock_client_cls.return_value = mock_client_instance
    api_key = "test_api_key_arg"

    gemini_tools = GeminiTools(api_key=api_key)

    assert gemini_tools.api_key == api_key
    mock_client_cls.assert_called_once_with(api_key=api_key)
    assert gemini_tools.client == mock_client_instance
    mock_getenv.assert_not_called()  # Shouldn't check env var if key is provided


@patch("agno.tools.models.gemini.getenv")
@patch("agno.tools.models.gemini.Client")
def test_gemini_tools_init_with_env_var(mock_client_cls, mock_getenv):
    """Test initialization with API key from environment variable."""
    mock_client_instance = MagicMock()
    mock_client_cls.return_value = mock_client_instance
    env_api_key = "test_api_key_env"
    mock_getenv.return_value = env_api_key

    gemini_tools = GeminiTools()

    assert gemini_tools.api_key == env_api_key
    mock_getenv.assert_called_once_with("GOOGLE_API_KEY")
    mock_client_cls.assert_called_once_with(api_key=env_api_key)
    assert gemini_tools.client == mock_client_instance


@patch("agno.tools.models.gemini.getenv")
@patch("agno.tools.models.gemini.Client")
def test_gemini_tools_init_no_api_key(mock_client_cls, mock_getenv):
    """Test initialization raises ValueError when no API key is found."""
    mock_getenv.return_value = None

    with pytest.raises(ValueError, match="GOOGLE_API_KEY not set"):
        GeminiTools()

    mock_getenv.assert_called_once_with("GOOGLE_API_KEY")
    mock_client_cls.assert_not_called()


@patch("agno.tools.models.gemini.getenv")
@patch("agno.tools.models.gemini.Client")
def test_gemini_tools_init_client_creation_fails(mock_client_cls, mock_getenv):
    """Test initialization raises ValueError if Client creation fails."""
    mock_getenv.return_value = "fake_key"
    mock_client_cls.side_effect = Exception("Client creation failed")

    with pytest.raises(ValueError, match="Failed to create Google GenAI Client"):
        GeminiTools()

    mock_getenv.assert_called_once_with("GOOGLE_API_KEY")
    mock_client_cls.assert_called_once_with(api_key="fake_key")


# Test generate_image method
@patch("agno.tools.models.gemini.getenv", return_value="fake_key")
@patch("agno.tools.models.gemini.Client")
@patch("agno.tools.models.gemini.uuid4", return_value=UUID("12345678-1234-5678-1234-567812345678"))
def test_generate_image_success(mock_uuid, mock_client_cls, mock_getenv, mock_agent, mock_successful_response):
    """Test successful image generation."""
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_images.return_value = mock_successful_response
    mock_client_cls.return_value = mock_client_instance

    gemini_tools = GeminiTools()
    prompt = "A picture of a cat"
    image_model = "imagen-test-model"
    gemini_tools.image_model = image_model  # Override default for test

    result = gemini_tools.generate_image(mock_agent, prompt)

    expected_media_id = "12345678-1234-5678-1234-567812345678"
    assert result == f"Image generated successfully with ID: {expected_media_id}"
    mock_client_instance.models.generate_images.assert_called_once_with(model=image_model, prompt=prompt)

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


@patch("agno.tools.models.gemini.getenv", return_value="fake_key")
@patch("agno.tools.models.gemini.Client")
def test_generate_image_api_error(mock_client_cls, mock_getenv, mock_agent):
    """Test image generation when the API call raises an exception."""
    mock_client_instance = MagicMock()
    api_error_message = "API unavailable"
    mock_client_instance.models.generate_images.side_effect = Exception(api_error_message)
    mock_client_cls.return_value = mock_client_instance

    gemini_tools = GeminiTools()
    prompt = "A picture of a dog"

    result = gemini_tools.generate_image(mock_agent, prompt)

    expected_error = f"Failed to generate image: Client or method not available ({api_error_message})"
    assert result == expected_error
    mock_client_instance.models.generate_images.assert_called_once_with(
        model=gemini_tools.image_model,  # Use default model
        prompt=prompt,
    )
    mock_agent.add_image.assert_not_called()


@patch("agno.tools.models.gemini.getenv", return_value="fake_key")
@patch("agno.tools.models.gemini.Client")
def test_generate_image_no_image_bytes(mock_client_cls, mock_getenv, mock_agent, mock_failed_response_no_bytes):
    """Test image generation when the API response lacks image bytes."""
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_images.return_value = mock_failed_response_no_bytes
    mock_client_cls.return_value = mock_client_instance

    gemini_tools = GeminiTools()
    prompt = "A picture of a bird"

    result = gemini_tools.generate_image(mock_agent, prompt)

    assert result == "Failed to generate image: No valid image data extracted."
    mock_client_instance.models.generate_images.assert_called_once_with(
        model=gemini_tools.image_model,  # Use default model
        prompt=prompt,
    )
    mock_agent.add_image.assert_not_called()
