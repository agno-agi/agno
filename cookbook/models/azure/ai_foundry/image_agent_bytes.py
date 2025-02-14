from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.azure import AzureAIFoundry

agent = Agent(
    model=AzureAIFoundry(id="Llama-3.2-11B-Vision-Instruct"),
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
