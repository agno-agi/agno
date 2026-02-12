"""
Mistral Image File Input Agent
==============================

Cookbook example for `mistral/image_file_input_agent.py`.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.mistral.mistral import MistralChat
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MistralChat(id="pixtral-12b-2409"),
    tools=[
        WebSearchTools()
    ],  # pixtral-12b-2409 is not so great at tool calls, but it might work.
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

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
