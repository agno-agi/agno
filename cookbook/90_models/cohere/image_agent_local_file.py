"""
Cohere Image Agent Local File
=============================

Cookbook example for `cohere/image_agent_local_file.py`.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.cohere.chat import Cohere
from agno.utils.media import download_image

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Cohere(id="c4ai-aya-vision-8b"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

download_image(
    url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
    output_path=str(image_path),
)

agent.print_response(
    "Tell me about this image.",
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
