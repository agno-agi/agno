from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.replicate import ReplicateTools

"""Create an agent specialized for Replicate AI content generation"""

video_agent = Agent(
    name="Video Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ReplicateTools(
            model="tencent/hunyuan-video:847dfa8b01e739637fc76f480ede0c1d76408e1d694b830b5dfb8e547bf98405"
        )
    ],
    description="You are an AI agent that can generate videos using the Replicate API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_media` tool to create the video.",
        "Return the URL as raw to the user.",
        "Don't convert video URL to markdown or anything else.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

video_agent.print_response("Generate a video of a horse in the dessert.")
