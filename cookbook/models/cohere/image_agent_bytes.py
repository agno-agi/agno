from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.cohere.chat import Cohere

agent = Agent(
    model=Cohere(id="c4ai-aya-vision-8b"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

# Read the image file content as bytes
with open(image_path, "rb") as img_file:
    image_bytes = img_file.read()

agent.print_response(
    "Tell me about this image.",
    images=[
        Image(content=image_bytes),
    ],
    stream=True,
)
