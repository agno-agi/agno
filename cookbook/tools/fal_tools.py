from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.fal import FalTools

fal_agent = Agent(
    name="Fal Video Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[FalTools("fal-ai/hunyuan-video")],
    description="You are an AI agent that can generate videos using the Fal API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_media` tool to create the video.",
        "Return the URL as raw to the user.",
        "Don't convert video URL to markdown or anything else.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

fal_agent.print_response("Generate video of balloon in the ocean")
