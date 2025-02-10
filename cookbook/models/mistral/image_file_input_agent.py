from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.mistral.mistral import MistralChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=MistralChat(id="pixtral-12b-2409"),
    tools=[
        DuckDuckGoTools()
    ],  # pixtral-12b-2409 is not so great at tool calls, but it might work.
    show_tool_calls=True,
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpeg")

agent.print_response(
    "Tell me about this image and give me the latest news about it from duckduckgo.",
    images=[
        Image(filepath=image_path),
    ],
    stream=True,
)
