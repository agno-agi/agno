from pathlib import Path

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.aws import AwsBedrock


def test_image_input_bytes():
    """
    Only bytes input is supported for multimodal models
    """
    agent = Agent(model=AwsBedrock(id="amazon.nova-pro-v1:0"), markdown=True, telemetry=False, monitoring=False)

    image_path = Path(__file__).parent.parent.parent.joinpath("sample_image.jpg")

    # Read the image file content as bytes
    image_bytes = image_path.read_bytes()

    response = agent.run(
        "Tell me about this image.",
        images=[Image(content=image_bytes, format="jpeg")],
    )

    assert "bridge" in response.content.lower()
