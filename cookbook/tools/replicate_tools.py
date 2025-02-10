from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.replicate import ReplicateTools

"""Create an agent specialized for Replicate AI content generation"""

image_agent = Agent(
    name="Image Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ReplicateTools(model="luma/photon-flash")],
    description="You are an AI agent that can generate images using the Replicate API.",
    instructions=[
        "When the user asks you to create an image, use the `generate_media` tool to create the image.",
        "Return the URL as raw to the user.",
        "Don't convert image URL to markdown or anything else.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

image_agent.print_response("Generate an image of a horse in the dessert.")
