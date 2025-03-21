from agno.agent.agent import Agent
from agno.media import File, Image
from agno.models.openai.responses import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools


def test_image_input():
    """Test image input with the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
    assert "san francisco" in response.content.lower()


def test_multimodal_with_tools():
    """Test multimodal input with tool use in the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this bridge and look up its current status.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    # Verify content includes image analysis and tool usage
    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()

    # Check for tool call
    assert any(msg.tool_calls for msg in response.messages if hasattr(msg, "tool_calls") and msg.tool_calls)


def test_file_upload():
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[{"type": "file_search"}],
        markdown=True,
    )

    response = agent.run(
        "Summarize the contents of the attached file.",
        files=[
            File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
        ],
    )
    assert response.content is not None

    # Responses API does not return citations for files yet
    # assert response.citations is not None
