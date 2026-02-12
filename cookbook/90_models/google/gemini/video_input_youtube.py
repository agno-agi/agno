"""
Google Video Input Youtube
==========================

Cookbook example for `google/gemini/video_input_youtube.py`.
"""

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    markdown=True,
)

agent.print_response(
    "Tell me about this video?",
    videos=[Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0")],
)

# Video upload via URL is also supported with Vertex AI

# agent = Agent(
#     model=Gemini(id="gemini-3-flash-preview", vertexai=True),
#     markdown=True,
# )

# agent.print_response("Tell me about this video?", videos=[Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0")])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
