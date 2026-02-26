"""
Video Understanding - Analyze Video Content
=============================================
Pass video files or YouTube URLs to Gemini for scene analysis and Q&A.

Key concepts:
- Video(content=..., format=...): Pass video bytes with format (mp4, etc.)
- Video(url=...): Pass a YouTube URL directly
- Native capability: No ffmpeg or video processing libraries needed
- Scene understanding: The model processes visual and audio tracks together

Example prompts to try:
- "Describe and summarize this video"
- "What are the key moments in this video?"
- "How many people appear in this video?"
- "What is the overall mood of this video?"
"""

import httpx
from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a video analysis expert. Describe the key scenes and provide
a clear summary.

## Rules

- Describe scenes chronologically
- Note any text, logos, or titles that appear
- Identify the overall theme or message
- Mention audio elements when relevant\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
video_agent = Agent(
    name="Video Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- From bytes content ---
    print("--- Analyzing video from bytes ---\n")
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Video input methods:

1. From URL (download first)
   response = httpx.get("https://example.com/video.mp4")
   videos=[Video(content=response.content, format="mp4")]

2. From local file
   video_bytes = Path("clip.mp4").read_bytes()
   videos=[Video(content=video_bytes, format="mp4")]

3. From YouTube (pass URL directly)
   videos=[Video(url="https://www.youtube.com/watch?v=...")]

Use cases for music/film/gaming:
- Analyze music videos for visual themes and mood
- Break down film scenes for editing review
- Review game trailers for content and pacing
- Extract key moments from livestream recordings
"""
