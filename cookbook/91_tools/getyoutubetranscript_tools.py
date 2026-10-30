"""
GetYouTubeTranscript Tools
=============================

Demonstrates GetYouTubeTranscript tools for fetching YouTube transcripts,
searching YouTube, and listing a channel's videos.

Requires: GETYOUTUBETRANSCRIPT_API_KEY environment variable.
Get your key at https://getyoutubetranscript.com
"""

from agno.agent import Agent
from agno.tools.getyoutubetranscript import GetYouTubeTranscriptTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Transcript only (default)
agent = Agent(
    tools=[GetYouTubeTranscriptTools()],
    description="You are a YouTube assistant that answers questions from video transcripts.",
    instructions=[
        "Fetch the transcript of the video the user gives you before answering.",
        "Base your answer only on the transcript and mention the video title.",
    ],
)

# Example 2: Transcripts with timestamps, plus search and channel listing
research_agent = Agent(
    tools=[GetYouTubeTranscriptTools(all=True)],
    description="You are a research agent that finds YouTube videos and quotes them.",
    instructions=[
        "Use search_youtube to find relevant videos, or list_channel_videos to browse a channel.",
        "Fetch transcripts with timestamps=True when you need to cite a moment in a video.",
        "Quote the start time in seconds next to each quote.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Summarize https://youtu.be/5e37ZT3SQbk in five bullet points.",
        markdown=True,
        stream=True,
    )

    research_agent.print_response(
        "Find a video about building AI agents, then quote one key point with its timestamp.",
        markdown=True,
        stream=True,
    )
