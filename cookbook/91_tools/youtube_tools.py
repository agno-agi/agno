"""
YouTubeTools - fetch video metadata, transcripts, and timestamps.

Setup:
    pip install youtube_transcript_api

Available tools:
    - get_metadata: Fetch video title, author, thumbnail (default: True)
    - get_transcript: Fetch full transcript text (default: False)
    - get_timestamps: Fetch transcript with timestamps (default: False)

Proxy support (for IP bans):
    YouTubeTools(proxy="http://user:pass@host:port", ...)
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.youtube import YouTubeTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        YouTubeTools(
            get_transcript=True,
            get_metadata=True,
            get_timestamps=True,
        )
    ],
    description="You are a YouTube agent. Fetch video data and answer questions.",
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Summarize this video https://www.youtube.com/watch?v=Iv9dewmcFbs&t",
        stream=True,
    )
