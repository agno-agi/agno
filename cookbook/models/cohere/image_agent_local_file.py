from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.cohere.chat import Cohere

agent = Agent(
    model=Cohere(id="c4ai-aya-vision-8b"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

agent.print_response(
    "Tell me about this image.",
    images=[
        Image(filepath=image_path),
    ],
    stream=True,
)
