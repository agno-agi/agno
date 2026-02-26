"""
12. Video Understanding
=======================
Gemini can process video files -- describe scenes, extract key moments,
and answer questions about the content.

Supports:
- Video from bytes content (downloaded files)
- YouTube URLs (pass directly)

Run:
    python cookbook/gemini_3/12_video_input.py
"""

import httpx

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
video_agent = Agent(
    name="Video Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="You are a video analysis expert. Describe the key scenes and provide a clear summary.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- From bytes content ---
    print("--- Analyzing video from bytes ---\n")
    url = "https://agno-public.s3.amazonaws.com/demo/sample-video.mp4"
    response = httpx.get(url)

    video_agent.print_response(
        "Describe and summarize this video.",
        videos=[
            Video(content=response.content, format="mp4"),
        ],
        stream=True,
    )

    # --- From YouTube URL ---
    print("\n--- Analyzing YouTube video ---\n")
    video_agent.print_response(
        "Tell me about this video.",
        videos=[Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0")],
        stream=True,
    )
