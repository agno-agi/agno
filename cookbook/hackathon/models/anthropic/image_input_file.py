from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20241022"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

image_path = Path(__file__).parent.parent.parent.joinpath("data/sample_image.jpg")

agent.print_response(
    "Tell me about this image and give me the latest news about it.",
    images=[Image(filepath=image_path)],
    stream=True,
)
