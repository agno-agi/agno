import base64
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools.models.nebius import NebiusTools


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


# Fixture for mock NebiusTools with mock client
@pytest.fixture
def mock_nebius_tools(mock_client):
    with patch("agno.tools.models.nebius.Nebius") as mock_nebius:
        mock_nebius_instance = MagicMock()
        mock_nebius_instance.get_client.return_value = mock_client
        mock_nebius.return_value = mock_nebius_instance

        nebius_tools = NebiusTools(api_key="fake_test_key")
        nebius_tools._nebius_client = mock_client
        return nebius_tools


# Fixture for successful API response
@pytest.fixture
def mock_successful_response():
    mock_response = MagicMock()
    mock_data = MagicMock()
    mock_data.b64_json = base64.b64encode(b"fake_image_base64")
    mock_response.data = [mock_data]
    return mock_response


# Fixture for failed API response (no image data)
@pytest.fixture
def mock_failed_response_no_data():
    mock_response = MagicMock()
    mock_response.data = []  # Empty list to simulate no images generated
    return mock_response


# Test Initialization
def test_nebius_tools_init_with_api_key_arg():
    """Test initialization with API key provided as an argument."""
    api_key = "test_api_key_arg"

    with patch("agno.tools.models.nebius.Nebius") as mock_nebius_cls:
        mock_nebius_instance = MagicMock()
        mock_client_instance = MagicMock()
        mock_nebius_instance.get_client.return_value = mock_client_instance
        mock_nebius_cls.return_value = mock_nebius_instance

        nebius_tools = NebiusTools(api_key=api_key)

        assert nebius_tools.api_key == api_key
        assert nebius_tools._nebius_client is None


def test_nebius_tools_init_with_env_var():
    """Test initialization with API key from environment variable."""
    env_api_key = "test_api_key_env"

    def mock_getenv_side_effect(var_name):
        if var_name == "NEBIUS_API_KEY":
            return env_api_key
        return None

    with patch("agno.tools.models.nebius.getenv", side_effect=mock_getenv_side_effect) as mock_getenv:
        with patch("agno.tools.models.nebius.Nebius") as mock_nebius_cls:
            mock_nebius_instance = MagicMock()
            mock_client_instance = MagicMock()
            mock_nebius_instance.get_client.return_value = mock_client_instance
            mock_nebius_cls.return_value = mock_nebius_instance

            nebius_tools = NebiusTools()

            assert nebius_tools.api_key == env_api_key
            assert nebius_tools._nebius_client is None
            assert mock_getenv.called


def test_nebius_tools_init_no_api_key():
    """Test initialization raises ValueError when no API key is found."""

    def mock_getenv_side_effect(var_name):
        return None

    with patch("agno.tools.models.nebius.getenv", side_effect=mock_getenv_side_effect) as mock_getenv:
        with pytest.raises(ValueError, match="NEBIUS_API_KEY not set"):
            NebiusTools()

        assert mock_getenv.called


# Test _get_client method
def test_get_client_lazy_initialization():
    """Test that client is lazily initialized."""
    with patch("agno.tools.models.nebius.Nebius") as mock_nebius_cls:
        mock_nebius_instance = MagicMock()
        mock_client = MagicMock()
        mock_nebius_instance.get_client.return_value = mock_client
        mock_nebius_cls.return_value = mock_nebius_instance

        nebius_tools = NebiusTools(api_key="test_api_key")

        # Client should not be initialized yet
        assert nebius_tools._nebius_client is None

        # Get client should initialize it
        client = nebius_tools._get_client()

        assert client == mock_client
        assert nebius_tools._nebius_client == mock_client
        mock_nebius_instance.get_client.assert_called_once()


# Test generate_image method
def test_generate_image_success(mock_nebius_tools, mock_agent, mock_successful_response):
    """Test successful image generation."""
    mock_client = mock_nebius_tools._get_client()
    mock_client.images.generate.return_value = mock_successful_response

    with patch("agno.tools.models.nebius.uuid4", return_value=UUID("12345678-1234-5678-1234-567812345678")):
        prompt = "A picture of a cat"

        result = mock_nebius_tools.generate_image(mock_agent, prompt)

        assert result == "Image generated successfully."
        mock_client.images.generate.assert_called_once_with(
            model=mock_nebius_tools.image_model,
            prompt=prompt,
            response_format="b64_json",
            size="1024x1024",
            quality="standard",
        )

        mock_agent.add_image.assert_called_once()
        call_args = mock_agent.add_image.call_args[0]
        image_artifact = call_args[0]

        assert isinstance(image_artifact, ImageArtifact)
        assert image_artifact.id == "12345678-1234-5678-1234-567812345678"
        assert image_artifact.original_prompt == prompt
        assert image_artifact.mime_type == "image/png"
        assert image_artifact.content == b"fake_image_base64"


def test_generate_image_no_data(mock_nebius_tools, mock_agent, mock_failed_response_no_data):
    """Test image generation when no data is returned."""
    mock_client = mock_nebius_tools._get_client()
    mock_client.images.generate.return_value = mock_failed_response_no_data

    prompt = "A picture of a cat"

    result = mock_nebius_tools.generate_image(mock_agent, prompt)

    assert result == "Failed to generate image: No data received from API."
    mock_client.images.generate.assert_called_once()
    mock_agent.add_image.assert_not_called()


def test_generate_image_api_error(mock_nebius_tools, mock_agent):
    """Test image generation when API call raises an exception."""
    mock_client = mock_nebius_tools._get_client()
    error_message = "API Error"
    mock_client.images.generate.side_effect = Exception(error_message)

    prompt = "A picture of a cat"

    result = mock_nebius_tools.generate_image(mock_agent, prompt)

    expected_error = f"Failed to generate image: {error_message}"
    assert result == expected_error
    mock_client.images.generate.assert_called_once()
    mock_agent.add_image.assert_not_called()


# Test with different image parameters
def test_generate_image_with_custom_params():
    """Test image generation with custom parameters."""
    with patch("agno.tools.models.nebius.Nebius") as mock_nebius_cls:
        mock_nebius_instance = MagicMock()
        mock_client = MagicMock()
        mock_data = MagicMock()
        mock_data.b64_json = "fake_image_base64"
        mock_response = MagicMock()
        mock_response.data = [mock_data]

        mock_client.images.generate.return_value = mock_response
        mock_nebius_instance.get_client.return_value = mock_client
        mock_nebius_cls.return_value = mock_nebius_instance

        custom_model = "custom-model"
        custom_quality = "hd"
        custom_size = "2048x2048"
        custom_style = "vivid"

        nebius_tools = NebiusTools(
            api_key="test_key",
            image_model=custom_model,
            image_quality=custom_quality,
            image_size=custom_size,
            image_style=custom_style,
        )

        mock_agent = MagicMock(spec=Agent)
        prompt = "A picture of a dog"

        with patch("agno.tools.models.nebius.uuid4", return_value=UUID("12345678-1234-5678-1234-567812345678")):
            nebius_tools.generate_image(mock_agent, prompt)

            mock_client.images.generate.assert_called_once_with(
                model=custom_model,
                prompt=prompt,
                response_format="b64_json",
                size=custom_size,
                quality=custom_quality,
                style=custom_style,
            )
