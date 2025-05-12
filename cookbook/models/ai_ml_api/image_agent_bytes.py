from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.ai_ml_api import AIMlAPI

agent = Agent(
    model=AIMlAPI(id="meta-llama/Llama-Vision-Free"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

# Read the image file content as bytes
image_bytes = image_path.read_bytes()

agent.print_response(
    "Tell me about this image",
    images=[
        Image(content=image_bytes),
    ],
    stream=True,
)
