"""
Video Caption
=============================

Please install dependencies using:.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.moviepy_video import MoviePyVideoTools
from agno.tools.openai import OpenAITools

video_tools = MoviePyVideoTools(
    process_video=True, generate_captions=True, embed_captions=True
)

openai_tools = OpenAITools()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
video_caption_agent = Agent(
    name="Video Caption Generator Agent",
    model=OpenAIResponses(
        id="gpt-4o",
    ),
    tools=[video_tools, openai_tools],
    description="You are an AI agent that can generate and embed captions for videos.",
    instructions=[
        "When a user provides a video, process it to generate captions.",
        "Use the video processing tools in this sequence:",
        "1. Extract audio from the video using extract_audio",
        "2. Transcribe the audio using transcribe_audio",
        "3. Generate SRT captions using create_srt",
        "4. Embed captions into the video using embed_captions",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    video_caption_agent.print_response(
        "Generate captions for {video with location} and embed them in the video"
    )
