from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

agent.print_response(
    "Tell me about this video?",
    videos=[Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0")],
)

# Video upload via URL is also supported with Vertex AI

# agent = Agent(
#     model=Gemini(id="gemini-2.0-flash-exp", vertexai=True),
#     markdown=True,
# )

# agent.print_response("Tell me about this video?", videos=[Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0")])
