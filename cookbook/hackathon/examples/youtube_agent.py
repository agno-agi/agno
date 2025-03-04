from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.youtube import YouTubeTools

youtube_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YouTubeTools()],
    show_tool_calls=True,
    markdown=True,
)

if __name__ == "__main__":
    youtube_agent.print_response(
        "Analyze this video: https://www.youtube.com/watch?v=zjkBMFhNj_g", stream=True
    )
