from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models_labs import ModelsLabTools

video_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools()],
    description="You are an AI agent that can generate videos using the ModelsLabs API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_media` tool to create the video.",
        "The video will be displayed in the UI automatically below your response, so you don't need to show the video URL in your response.",
        "Politely and courteously let the user know that the video has been generated and will be displayed below as soon as its ready.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

video_agent.run("Generate a video of a cat playing with a ball")
for video in video_agent.run_response.videos:
    print("Video File URL:", video.url)
