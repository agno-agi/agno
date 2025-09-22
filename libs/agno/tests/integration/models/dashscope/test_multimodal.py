from pathlib import Path

import pytest

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope


def test_image_input_url():
    agent = Agent(model=DashScope(id="qwen-vl-plus"), markdown=True, telemetry=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_image_input_bytes():
    agent = Agent(model=DashScope(id="qwen-vl-plus"), telemetry=False)

    image_path = Path(__file__).parent.parent.joinpath("sample_image.jpg")

    # Read the image file content as bytes
    image_bytes = image_path.read_bytes()

    response = agent.run(
        "Tell me about this image.",
        images=[Image(content=image_bytes)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


@pytest.mark.asyncio
async def test_async_image_input_stream():
    agent = Agent(model=DashScope(id="qwen-vl-plus"), markdown=True, telemetry=False)

    image_path = Path(__file__).parent.parent.joinpath("sample_image.jpg")
    image_bytes = image_path.read_bytes()

    response_stream = await agent.arun(
        "Describe this image in detail.", images=[Image(content=image_bytes, format="jpeg")], stream=True
    )

    responses = []
    async for chunk in response_stream:
        responses.append(chunk)
        assert chunk.content is not None

    assert len(responses) > 0

    full_content = ""
    for r in responses:
        full_content += r.content or ""

    assert "bridge" in full_content.lower()
