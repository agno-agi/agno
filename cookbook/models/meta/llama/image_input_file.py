from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.meta import Llama

agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    markdown=True,
)
# Please download the image using
# wget https://upload.wikimedia.org/wikipedia/commons/b/bf/Krakow_-_Kosciol_Mariacki.jpg
image_path = Path(__file__).parents[4].joinpath("Krakow_-_Kosciol_Mariacki.jpg")

agent.print_response(
    "Tell me about this image?",
    images=[Image(filepath=image_path)],
    stream=True,
)
