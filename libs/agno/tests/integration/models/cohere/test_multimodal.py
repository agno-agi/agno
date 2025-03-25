from pathlib import Path

import pytest

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.cohere.chat import Cohere
from agno.tools.duckduckgo import DuckDuckGoTools


def test_image_input():
    agent = Agent(
        model=Cohere(id="c4ai-aya-vision-8b"),
        add_history_to_messages=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()

    # Just check it doesn't break on subsequent messages
    response = agent.run("Where can I find more information?")
    assert [message.role for message in response.messages] == ["system", "user", "assistant", "user", "assistant"]


def test_image_input_bytes():
    agent = Agent(model=Cohere(id="c4ai-aya-vision-8b"), telemetry=False, monitoring=False)

    image_path = Path(__file__).parent.parent.joinpath("sample_image.jpg")

    # Read the image file content as bytes
    image_bytes = image_path.read_bytes()

    response = agent.run(
        "Tell me about this image.",
        images=[Image(content=image_bytes)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_image_input_local_file():
    agent = Agent(model=Cohere(id="c4ai-aya-vision-8b"), telemetry=False, monitoring=False)

    image_path = Path(__file__).parent.parent.joinpath("sample_image.jpg")

    response = agent.run(
        "Tell me about this image.",
        images=[Image(filepath=image_path)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


@pytest.mark.skip(reason="Image with tool call is not supported yet.")
def test_image_input_with_tool_call():
    agent = Agent(
        model=Cohere(id="c4ai-aya-vision-8b"),
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
