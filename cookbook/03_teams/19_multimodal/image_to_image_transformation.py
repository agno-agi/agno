"""
Image To Image Transformation
=============================

Demonstrates collaborative style planning and image transformation.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.fal import FalTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
style_advisor = Agent(
    name="Style Advisor",
    role="Analyze and recommend artistic styles and transformations",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Analyze the input image and transformation request",
        "Provide style recommendations and enhancement suggestions",
        "Consider artistic elements like composition, lighting, and mood",
    ],
)

image_transformer = Agent(
    name="Image Transformer",
    role="Transform images using AI tools",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[FalTools()],
    instructions=[
        "Use the `image_to_image` tool to generate transformed images",
        "Apply the recommended styles and transformations",
        "Return the image URL as provided without markdown conversion",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
transformation_team = Team(
    name="Image Transformation Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[style_advisor, image_transformer],
    instructions=[
        "Transform images with artistic style and precision.",
        "Style Advisor: First analyze transformation requirements and recommend styles.",
        "Image Transformer: Apply transformations using AI tools with style guidance.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    transformation_team.print_response(
        "a cat dressed as a wizard with a background of a mystic forest. Make it look like 'https://fal.media/files/koala/Chls9L2ZnvuipUTEwlnJC.png'",
        stream=True,
    )
