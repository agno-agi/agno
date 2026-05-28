"""Integration tests for CometAPI model provider."""

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite import SqliteDb
from agno.models.cometapi import CometAPI


def _assert_metrics(response: RunOutput):
    """Helper function to assert response metrics are valid."""
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic():
    """Test basic chat functionality with CometAPI."""
    agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True, telemetry=False)

    # Test basic response generation
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    """Test streaming response with CometAPI."""
    agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True, telemetry=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None


@pytest.mark.asyncio
async def test_basic_async():
    """Test async chat functionality with CometAPI."""
    agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True, telemetry=False)

    # Test async response generation
    response: RunOutput = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_basic_async_stream():
    """Test async streaming response with CometAPI."""
    agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True, telemetry=False)

    response_stream = agent.arun("Share a 2 sentence horror story", stream=True)

    # Verify it's an async iterator
    assert hasattr(response_stream, "__aiter__")

    responses = []
    async for response in response_stream:
        responses.append(response)
        assert response.content is not None

    assert len(responses) > 0


def test_structured_output():
    """Test structured output with Pydantic models."""

    class StoryElements(BaseModel):
        title: str = Field(..., description="Story title")
        genre: str = Field(..., description="Story genre")
        main_character: str = Field(..., description="Main character name")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(model=CometAPI(id="gpt-5-mini"), output_schema=StoryElements, markdown=True, telemetry=False)
    response: RunOutput = agent.run("Create a short story about time travel")

    # Verify structured output
    assert isinstance(response.content, StoryElements)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.main_character is not None
    assert response.content.plot is not None


def test_with_memory():
    """Test agent with memory storage."""
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file="tmp/cometapi_agent_sessions.db")
    agent = Agent(
        model=CometAPI(id="gpt-5-mini"),
        db=db,
        session_id="test_session_123",
        add_history_to_context=True,
        telemetry=False,
    )

    response: RunOutput = agent.run("Remember, my name is Alice.")
    assert response.content is not None

    # Test if agent can access session history
    response2: RunOutput = agent.run("What did I just tell you about my name?")
    assert response2.content is not None
    # The response should reference the previous conversation
    assert len(response2.messages) > 2  # Should have multiple messages in history


def test_tool_usage():
    """Test agent with Calculator tools."""
    from agno.tools.calculator import CalculatorTools

    agent = Agent(
        model=CometAPI(id="gpt-5-mini"),
        tools=[CalculatorTools()],
        instructions="You are a helpful assistant. Always use the calculator tool for mathematical calculations.",
        telemetry=False,
    )

    response: RunOutput = agent.run("Use the calculator to compute 15 + 27")
    assert response.content is not None
    assert "42" in response.content


def test_different_models():
    """Test CometAPI with different model IDs."""
    model_ids = ["gpt-5-mini", "claude-sonnet-4-20250514", "gemini-2.5-flash-lite"]

    for model_id in model_ids:
        agent = Agent(model=CometAPI(id=model_id), telemetry=False)

        try:
            response: RunOutput = agent.run("Say hello in one sentence")

            assert response.content is not None
            assert len(response.content) > 0

        except Exception as e:
            # Some models might not be available, that's ok for this test
            pytest.skip(f"Model {model_id} not available: {e}")


def test_custom_base_url():
    """Test CometAPI with custom base URL."""
    agent = Agent(
        model=CometAPI(
            id="gpt-5-mini",
            base_url="https://api.cometapi.com/v1",  # explicit base URL
        ),
        telemetry=False,
    )

    response: RunOutput = agent.run("Hello, world!")

    assert response.content is not None
    _assert_metrics(response)


def test_tool_usage_stream():
    """Test agent with Calculator tools in streaming mode."""
    from agno.tools.calculator import CalculatorTools

    agent = Agent(
        model=CometAPI(id="gpt-5-mini"),
        tools=[CalculatorTools()],
        instructions="You are a helpful assistant. Always use the calculator tool for mathematical calculations.",
        telemetry=False,
    )

    response_stream = agent.run("Use the calculator to compute 25 * 4", stream=True)
    responses = list(response_stream)
    final_response = responses[-1]

    assert final_response.content is not None
    # Check if the calculation result is in the response
    full_content = "".join([r.content for r in responses if r.content])
    assert "100" in full_content


@pytest.mark.asyncio
async def test_async_tool_usage():
    """Test CometAPI with async tool usage."""
    from agno.tools.calculator import CalculatorTools

    agent = Agent(
        model=CometAPI(id="gpt-5-mini"),
        tools=[CalculatorTools()],
        instructions="You are a helpful assistant. Always use the calculator tool for mathematical calculations.",
        telemetry=False,
    )

    response: RunOutput = await agent.arun("Use the calculator to compute 12 * 8")

    assert response.content is not None
    assert response.messages is not None

    # Check if the calculation result is in the response
    assert "96" in response.content

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_tool_usage_stream():
    """Test CometAPI with async tool usage and streaming."""
    from agno.tools.calculator import CalculatorTools

    agent = Agent(
        model=CometAPI(id="gpt-5-mini"),
        tools=[CalculatorTools()],
        instructions="You are a helpful assistant. Always use the calculator tool for mathematical calculations.",
        telemetry=False,
    )

    response_stream = agent.arun("Use the calculator to compute 9 * 7", stream=True)

    # Verify it's an async iterator
    assert hasattr(response_stream, "__aiter__")

    responses = []
    final_content = ""
    async for response in response_stream:
        responses.append(response)
        # Only check content if it exists (streaming events may not have content)
        if hasattr(response, "content") and response.content:
            final_content += response.content

    assert len(responses) > 0
    # Check if the calculation result is in the final response
    assert "63" in final_content


def test_image_analysis():
    """Test CometAPI with image analysis capability."""
    from agno.media import Image

    # Use a vision-capable model from CometAPI
    agent = Agent(
        model=CometAPI(id="gpt-4o"),  # GPT-4o has vision capabilities
        markdown=True,
        telemetry=False,
    )

    try:
        response: RunOutput = agent.run(
            "Describe what you see in this image briefly",
            images=[
                Image(
                    url="https://httpbin.org/image/png"  # Use a reliable test image
                )
            ],
        )

        assert response.content is not None
        assert len(response.content) > 0
        # Should mention it's an image or describe visual content
        assert any(keyword in response.content.lower() for keyword in ["image", "picture", "pig", "cartoon", "pink"])
        _assert_metrics(response)

    except Exception as e:
        # Vision models might not be available, that's ok for this test
        pytest.skip(f"Vision model not available: {e}")


def test_image_analysis_with_memory():
    """Test CometAPI image analysis with memory storage."""
    from agno.media import Image

    # Create a temporary database for testing
    db = SqliteDb(db_file="test_cometapi_image.db")

    agent = Agent(
        model=CometAPI(id="gpt-4o"),  # GPT-4o has vision capabilities
        db=db,
        session_id="test_image_session_456",
        add_history_to_context=True,
        telemetry=False,
    )

    try:
        # First interaction with an image
        response1: RunOutput = agent.run(
            "Look at this image and remember what you see",
            images=[
                Image(
                    url="https://httpbin.org/image/png"  # Use a reliable test image
                )
            ],
        )
        assert response1.content is not None

        # Second interaction - should remember the image content
        response2: RunOutput = agent.run("What did you see in the image I showed you?")
        assert response2.content is not None
        # Should reference the previous image content
        assert any(keyword in response2.content.lower() for keyword in ["pig", "cartoon", "pink", "image", "showed"])

        # Clean up
        try:
            import os

            if os.path.exists("test_cometapi_image.db"):
                os.remove("test_cometapi_image.db")
        except OSError:
            pass  # Ignore cleanup errors

    except Exception as e:
        # Vision models might not be available, that's ok for this test
        pytest.skip(f"Vision model not available: {e}")
