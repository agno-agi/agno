from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.meta import LlamaOpenAI
from agno.utils.media import download_image

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

download_image(
    url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
    output_path=str(image_path),
)

agent.print_response(
    "Tell me about this image?",
    images=[Image(filepath=image_path)],
    stream=True,
)
