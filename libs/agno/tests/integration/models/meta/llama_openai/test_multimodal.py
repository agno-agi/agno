from pathlib import Path

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.meta import Llama
from agno.utils.media import download_image

image_path = Path(__file__).parent.joinpath("sample.jpg")

download_image(
    url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
    output_path=str(image_path),
)


def test_image_input_file():
    agent = Agent(
        model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"), markdown=True, telemetry=False, monitoring=False
    )

    response = agent.run(
        "Tell me about this image?",
        images=[Image(filepath=image_path)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_image_input_bytes():
    agent = Agent(
        model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"), markdown=True, telemetry=False, monitoring=False
    )

    image_bytes = image_path.read_bytes()

    response = agent.run(
        "Tell me about this image?",
        images=[Image(content=image_bytes)],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
