from agno.agent import Agent
from agno.tools.youtube import YouTubeTools

agent = Agent(
    tools=[YouTubeTools()],
    show_tool_calls=True,
    description="You are a YouTube agent. Obtain the captions of a YouTube video and answer questions.",
)
agent.print_response(
    "Summarize this video https://www.youtube.com/watch?v=Iv9dewmcFbs&t", markdown=True
)
