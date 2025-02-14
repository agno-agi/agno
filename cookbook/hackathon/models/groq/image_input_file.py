from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.groq import Groq

agent = Agent(model=Groq(id="llama-3.2-90b-vision-preview"))

image_path = Path(__file__).parent.parent.parent.joinpath("data/sample_image.jpg")

agent.print_response(
    "Tell me about this image",
    images=[Image(filepath=image_path)],
    stream=True,
)
