"""
Image To Image
=============================

Image To Image.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.fal import FalTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    id="image-to-image",
    name="Image to Image Agent",
    tools=[FalTools()],
    markdown=True,
    instructions=[
        "You have to use the `image_to_image` tool to generate the image.",
        "You are an AI agent that can generate images using the Fal AI API.",
        "You will be given a prompt and an image URL.",
        "You have to return the image URL as provided, don't convert it to markdown or anything else.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "a cat dressed as a wizard with a background of a mystic forest. Make it look like 'https://fal.media/files/koala/Chls9L2ZnvuipUTEwlnJC.png'",
        stream=True,
    )
