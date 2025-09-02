from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.replicate import ReplicateTools

"""Create an agent specialized for Replicate AI content generation"""

# Example 1: Enable specific Replicate functions
image_agent = Agent(
    name="Image Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ReplicateTools(model="luma/photon-flash", enable_generate_media=True)],
    description="You are an AI agent that can generate images using the Replicate API.",
    instructions=[
        "When the user asks you to create an image, use the `generate_media` tool to create the image.",
        "Return the URL as raw to the user.",
        "Don't convert image URL to markdown or anything else.",
    ],
    markdown=True,
)

# Example 2: Enable all Replicate functions
full_agent = Agent(
    name="Full Replicate Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ReplicateTools(model="minimax/video-01", all=True)],
    description="You are an AI agent that can generate various media using Replicate models.",
    instructions=[
        "Use the Replicate API to generate images or videos based on user requests.",
        "Return the generated media URL to the user.",
    ],
    markdown=True,
)

image_agent.print_response("Generate an image of a horse in the dessert.")
