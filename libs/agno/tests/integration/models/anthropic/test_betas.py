"""Tests for Anthropic beta features support."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude


def _create_mock_response():
    """Create a properly structured mock response."""
    mock_content_block = MagicMock()
    mock_content_block.type = "text"
    mock_content_block.text = "Test response"
    mock_content_block.citations = None

    # Create a proper usage mock with all required attributes
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20
    mock_usage.cache_creation_input_tokens = None
    mock_usage.cache_read_input_tokens = None

    mock_response = MagicMock()
    mock_response.id = "msg_test123"
    mock_response.model = "claude-sonnet-4-5-20250929"
    mock_response.role = "assistant"
    mock_response.stop_reason = "end_turn"
    mock_response.content = [mock_content_block]
    mock_response.usage = mock_usage

    return mock_response


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client for testing beta features."""
    with patch("agno.models.anthropic.claude.AnthropicClient") as mock_client_class:
        mock_client = MagicMock()
        mock_beta_messages = MagicMock()
        mock_messages = MagicMock()

        # Setup mock client structure
        mock_client.beta.messages = mock_beta_messages
        mock_client.messages = mock_messages
        mock_client.is_closed.return_value = False

        # Setup mock responses
        mock_beta_messages.create.return_value = _create_mock_response()
        mock_messages.create.return_value = _create_mock_response()

        mock_client_class.return_value = mock_client

        yield mock_client


@pytest.fixture(scope="module")
def claude_model():
    """Fixture that provides a Claude model and reuses it across all tests in the module."""
    return Claude(id="claude-sonnet-4-20250514", betas=["context-1m-2025-08-07"])


def test_betas_parameter_in_request_params():
    """Test that betas parameter is included in request params when provided."""
    betas = ["context-1m-2025-08-07", "custom-beta-feature"]
    model = Claude(id="claude-sonnet-4-20250514", betas=betas)

    request_params = model.get_request_params()

    assert "betas" in request_params
    assert request_params["betas"] == betas


def test_no_betas_parameter_when_not_provided():
    """Test that betas parameter is not included when not provided."""
    model = Claude(id="claude-sonnet-4-20250514")

    request_params = model.get_request_params()

    assert "betas" not in request_params


def test_has_beta_features_with_betas():
    """Test that _has_beta_features returns True when betas are provided."""
    model = Claude(id="claude-sonnet-4-20250514", betas=["context-1m-2025-08-07"])

    assert model._has_beta_features() is True


def test_has_beta_features_without_betas():
    """Test that _has_beta_features returns False when no beta features are enabled."""
    model = Claude(id="claude-sonnet-4-20250514")

    # Should return False when no beta features are enabled
    assert model._has_beta_features() is False


def test_beta_client_used_when_betas_provided(mock_anthropic_client):
    """Test that beta client is used when betas parameter is provided."""
    betas = ["context-1m-2025-08-07"]
    model = Claude(id="claude-sonnet-4-20250514", betas=betas)
    agent = Agent(model=model, telemetry=False)

    # Run the agent
    agent.run("Test message")

    # Verify that beta client was used
    mock_anthropic_client.beta.messages.create.assert_called_once()

    # Verify that regular client was NOT used
    mock_anthropic_client.messages.create.assert_not_called()

    # Verify that betas parameter was passed in the request
    call_kwargs = mock_anthropic_client.beta.messages.create.call_args[1]
    assert "betas" in call_kwargs
    assert call_kwargs["betas"] == betas


def test_regular_client_used_without_betas(mock_anthropic_client):
    """Test that regular client is used when no betas are provided."""
    model = Claude(id="claude-sonnet-4-20250514")
    agent = Agent(model=model, telemetry=False)

    # Run the agent
    agent.run("Test message")

    # Verify that regular client was used
    mock_anthropic_client.messages.create.assert_called_once()

    # Verify that beta client was NOT used
    mock_anthropic_client.beta.messages.create.assert_not_called()

    # Verify that betas parameter was not passed
    call_kwargs = mock_anthropic_client.messages.create.call_args[1]
    assert "betas" not in call_kwargs


def test_multiple_betas():
    """Test that multiple beta features can be specified."""
    betas = ["context-1m-2025-08-07", "feature-a", "feature-b"]
    model = Claude(id="claude-sonnet-4-20250514", betas=betas)

    request_params = model.get_request_params()

    assert request_params["betas"] == betas
    assert len(request_params["betas"]) == 3


def test_betas_with_skills():
    """Test that betas work alongside skills configuration."""
    betas = ["custom-beta"]
    model = Claude(
        id="claude-sonnet-4-20250514",
        betas=betas,
        skills=[{"type": "anthropic", "skill_id": "pptx", "version": "latest"}],
    )

    # Skills automatically add required betas
    assert model._has_beta_features() is True

    request_params = model.get_request_params()

    # Should include both custom betas and skills-required betas
    assert "betas" in request_params
    assert "custom-beta" in request_params["betas"]
    assert "code-execution-2025-08-25" in request_params["betas"]
    assert "skills-2025-10-02" in request_params["betas"]


@pytest.mark.integration
def test_betas_with_real_client(claude_model):
    """Test that betas work with a real client"""
    agent = Agent(model=claude_model, telemetry=False)

    # Assert betas are present
    assert agent.model.betas is not None  # type: ignore

    response = agent.run("What is 2+2? Answer in one sentence.")

    # Verify the response was correctly generated
    assert response is not None, "Response should not be None"
    assert response.content is not None, "Response content should not be None"


@pytest.mark.asyncio
async def test_async_beta_client_used_when_betas_provided():
    """Test that async beta client is used when betas parameter is provided."""
    with patch("agno.models.anthropic.claude.AsyncAnthropicClient") as mock_async_client_class:
        mock_async_client = MagicMock()
        mock_beta_messages = MagicMock()
        mock_messages = MagicMock()

        # Setup mock async client structure
        mock_async_client.beta.messages = mock_beta_messages
        mock_async_client.messages = mock_messages
        mock_async_client.is_closed.return_value = False

        # Setup async mock responses using AsyncMock
        mock_beta_messages.create = AsyncMock(return_value=_create_mock_response())
        mock_messages.create = AsyncMock(return_value=_create_mock_response())

        mock_async_client_class.return_value = mock_async_client

        betas = ["context-1m-2025-08-07"]
        model = Claude(id="claude-sonnet-4-20250514", betas=betas)
        agent = Agent(model=model, telemetry=False)

        # Run the agent asynchronously
        await agent.arun("Test message")

        # Verify that beta client was used
        mock_async_client.beta.messages.create.assert_called_once()

        # Verify that regular client was NOT used
        mock_async_client.messages.create.assert_not_called()

        # Verify that betas parameter was passed in the request
        call_kwargs = mock_async_client.beta.messages.create.call_args[1]
        assert "betas" in call_kwargs
        assert call_kwargs["betas"] == betas


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("os").getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set - skipping real API test",
)
async def test_betas_with_real_client_async(claude_model):
    """Test that betas work with a real async client.

    This integration test makes a real async API call to Anthropic to verify that:
    1. The beta API endpoint is successfully invoked asynchronously
    2. The response is properly formatted
    3. No errors occur when using beta features with async operations

    Note: Requires ANTHROPIC_API_KEY to be set in environment.
    """
    agent = Agent(model=claude_model, telemetry=False)

    # Use a simple message to minimize token usage
    response = await agent.arun("What is 2+2? Answer in one sentence.")

    # Verify response structure
    assert response is not None, "Response should not be None"
    assert response.content is not None, "Response content should not be None"
    assert len(response.content) > 0, "Response content should not be empty"

    # Verify we got a meaningful response
    assert isinstance(response.content, str), "Response content should be a string"
    assert len(response.content.strip()) > 0, "Response should contain non-empty content"

    # Verify the model was set correctly
    assert response.model is not None, "Response model should not be None"
    assert response.model == "claude-sonnet-4-20250514" or response.model.startswith("claude-"), (
        f"Expected Claude model, got {response.model}"
    )
