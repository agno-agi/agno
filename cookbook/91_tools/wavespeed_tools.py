"""
WaveSpeed Tools
=============================

Demonstrates WaveSpeed tools.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.wavespeed import WaveSpeedTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


wavespeed_agent = Agent(
    name="WaveSpeed Media Generator Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        WaveSpeedTools(
            image_model="bytedance/seedream-v5.0-pro",
            video_model="bytedance/seedance-2.5/text-to-video",
        )
    ],
    description="You are an AI agent that can generate images and videos using the WaveSpeed API.",
    instructions=[
        "When the user asks you to create an image, use the `generate_image` tool.",
        "When the user asks you to create a video, use the `generate_video` tool.",
        "Return the URL as raw to the user.",
        "Don't convert the media URL to markdown or anything else.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    wavespeed_agent.print_response(
        "Generate an image of a lighthouse on a stormy coast"
    )
