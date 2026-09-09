"""
yt-dlp — Video Research Agent
================================

A focused agent that takes a video URL, fetches yt-dlp metadata,
and summarizes it for research.

USE CASES:
- Quickly summarize a video's contents (title, uploader, description, tags)
- Filter videos by duration / channel before downloading
- Use as part of a wider research workflow

Prerequisites:
- pip install yt-dlp
- ffmpeg on PATH (for format merging)
- export OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

from yt_dlp_tools import YtDlpTools


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
video_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[YtDlpTools(download_dir="./tmp/youtube_research")],
    markdown=True,
    instructions=(
        "You research videos. Prefer extract_metadata for quick lookup. "
        "Only call download_video when the user explicitly asks to keep the file. "
        "Report results as plain markdown with title, uploader, duration."
    ),
)


# ---------------------------------------------------------------------------
# Run the agent (manually runnable entrypoint)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    video_agent.print_response(
        "Summarize this video and tell me who uploaded it: "
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        stream=True,
    )
