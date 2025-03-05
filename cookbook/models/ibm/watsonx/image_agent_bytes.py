from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.ibm import WatsonX
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=WatsonX(id="meta-llama/llama-3-2-11b-vision-instruct"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

# Read the image file content as bytes
with open(image_path, "rb") as img_file:
    image_bytes = img_file.read()

agent.print_response(
    "Tell me about this image and and give me the latest news about it.",
    images=[
        Image(content=image_bytes),
    ],
    stream=True,
)
