from pathlib import Path

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.ibm import WatsonX


def test_image_input():
    agent = Agent(model=WatsonX(id="meta-llama/llama-3-2-11b-vision-instruct"), telemetry=False, monitoring=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_image_input_bytes():
    agent = Agent(model=WatsonX(id="meta-llama/llama-3-2-11b-vision-instruct"), telemetry=False, monitoring=False)

    image_path = Path(__file__).parent.parent.parent.joinpath("sample_image.jpg")

    # Read the image file content as bytes
    image_bytes = image_path.read_bytes()

    response = agent.run(
        "Tell me about this image.",
        images=[Image(content=image_bytes)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
