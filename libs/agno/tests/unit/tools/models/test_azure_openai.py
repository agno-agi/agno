"""Unit tests for AzureOpenAITools class."""

from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent
from agno.tools.models.azure_openai import AzureOpenAITools


@pytest.fixture
def mock_agent():
    """Create a mock Agent instance."""
    agent = MagicMock(spec=Agent)
    return agent


@pytest.fixture
def azure_openai_tools():
    """Create an AzureOpenAITools instance with mocked credentials."""
    with patch.dict(
        "os.environ",
        {
            "AZURE_OPENAI_API_KEY": "test_api_key",
            "AZURE_OPENAI_ENDPOINT": "https://test-endpoint.openai.azure.com/",
            "AZURE_OPENAI_IMAGE_DEPLOYMENT": "test-deployment",
            "AZURE_OPENAI_API_VERSION": "2023-12-01-preview",
        },
    ):
        return AzureOpenAITools()


def test_initialization():
    """Test initialization with parameters."""
    with patch.dict(
        "os.environ",
        {
            "AZURE_OPENAI_API_KEY": "",
            "AZURE_OPENAI_ENDPOINT": "",
        },
    ):
        tools = AzureOpenAITools(
            api_key="custom_api_key",
            azure_endpoint="https://custom-endpoint.openai.azure.com/",
            api_version="2023-05-15",
            image_deployment="custom-deployment",
            image_model="dall-e-3",
        )

        assert tools.api_key == "custom_api_key"
        assert tools.azure_endpoint == "https://custom-endpoint.openai.azure.com/"
        assert tools.api_version == "2023-05-15"
        assert tools.image_deployment == "custom-deployment"
        assert tools.image_model == "dall-e-3"


def test_initialization_with_env_vars():
    """Test initialization with environment variables."""
    with patch.dict(
        "os.environ",
        {
            "AZURE_OPENAI_API_KEY": "env_api_key",
            "AZURE_OPENAI_ENDPOINT": "https://env-endpoint.openai.azure.com/",
            "AZURE_OPENAI_API_VERSION": "2023-07-01-preview",
            "AZURE_OPENAI_IMAGE_DEPLOYMENT": "env-deployment",
        },
    ):
        tools = AzureOpenAITools()

        assert tools.api_key == "env_api_key"
        assert tools.azure_endpoint == "https://env-endpoint.openai.azure.com/"
        assert tools.api_version == "2023-07-01-preview"
        assert tools.image_deployment == "env-deployment"
        assert tools.image_model == "dall-e-3"  # Default value


def test_tools_registration(azure_openai_tools):
    """Test that the proper tools are registered."""
    # The generate_image function should be registered
    function_names = [func.name for func in azure_openai_tools.functions.values()]
    assert "generate_image" in function_names


@patch("agno.tools.models.azure_openai.post")
def test_generate_image_success(mock_post, azure_openai_tools, mock_agent):
    """Test successful image generation."""
    # Configure the mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"url": "https://test-image-url.com/image.png", "revised_prompt": "A revised prompt for the image"}]
    }
    mock_post.return_value = mock_response

    # Call the generate_image function
    result = azure_openai_tools.generate_image(agent=mock_agent, prompt="A test prompt", size="1024x1024")

    # Verify the API call
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    # Check URL with more flexible assertion to accommodate potential double slashes
    assert "test-endpoint.openai.azure.com" in args[0]
    assert "openai/deployments/test-deployment/images/generations" in args[0]
    assert "api-version=" in args[0]
    assert kwargs["headers"]["api-key"] == "test_api_key"

    # Check the enforced parameters in the JSON payload
    assert kwargs["json"]["model"] == "dall-e-3"
    assert kwargs["json"]["size"] == "1024x1024"
    assert kwargs["json"]["style"] == "vivid"  # Default value
    assert kwargs["json"]["quality"] == "standard"  # Default value
    assert kwargs["json"]["n"] == 1  # Default value

    # Verify the agent interaction
    mock_agent.add_image.assert_called_once()

    # Check the return string
    assert "https://test-image-url.com/image.png" in result


@patch("agno.tools.models.azure_openai.post")
def test_generate_image_with_custom_parameters(mock_post, azure_openai_tools, mock_agent):
    """Test image generation with custom parameters."""
    # Configure the mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"url": "https://test-image-url.com/image.png", "revised_prompt": "A revised prompt for the image"}]
    }
    mock_post.return_value = mock_response

    # Call the generate_image function with custom parameters
    azure_openai_tools.generate_image(agent=mock_agent, prompt="A test prompt", size="1792x1024", style="vivid")

    # Verify the API call uses the correct deployment
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    # Check URL with more flexible assertion to accommodate potential double slashes
    assert "test-endpoint.openai.azure.com" in args[0]
    assert "openai/deployments/test-deployment/images/generations" in args[0]
    assert "api-version=" in args[0]

    # Verify all parameters are correctly passed
    assert kwargs["json"]["prompt"] == "A test prompt"
    assert kwargs["json"]["model"] == "dall-e-3"
    assert kwargs["json"]["quality"] == "standard"
    assert kwargs["json"]["style"] == "vivid"
    assert kwargs["json"]["size"] == "1792x1024"
    assert kwargs["json"]["n"] == 1  # Default for dall-e-3


@patch("agno.tools.models.azure_openai.post")
def test_generate_image_failure(mock_post, azure_openai_tools, mock_agent):
    """Test image generation failure handling."""
    # Configure the mock response for a failed API call
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request: Invalid prompt"
    mock_post.return_value = mock_response

    # Call the generate_image function
    result = azure_openai_tools.generate_image(agent=mock_agent, prompt="A test prompt")

    # Verify the error is properly handled
    assert "Error" in result
    assert "400" in result
    assert "Bad Request: Invalid prompt" in result

    # Make sure no image was added to the agent
    mock_agent.add_image.assert_not_called()


def test_invalid_parameters(azure_openai_tools, mock_agent):
    """Test automatic correction of invalid parameters."""
    # Setup mock response for successful API call
    with patch("agno.tools.models.azure_openai.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"url": "https://test-image-url.com/image.png", "revised_prompt": "A revised prompt for the image"}
            ]
        }
        mock_post.return_value = mock_response

        # Test with invalid size - should be corrected to 1024x1024
        azure_openai_tools.generate_image(agent=mock_agent, prompt="A test prompt for size", size="invalid-size")

        # Verify the API call used the corrected size
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["prompt"] == "A test prompt for size"
        assert kwargs["json"]["size"] == "1024x1024"
        assert kwargs["json"]["model"] == "dall-e-3"  # Default model
